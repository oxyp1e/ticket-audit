#!/usr/bin/env bash
# Build, push and deploy the read-only system to Azure Container Apps (ADR 8).
# Re-runnable: creates what's missing, updates the app to the new image otherwise.
#
#   deploy/deploy.sh            # build + push + deploy
#   deploy/deploy.sh --no-build # redeploy the current image (e.g. after rotating the access code)
#
# Needs: az (signed in), docker with buildx, gh with write:packages, and in .env:
#   AZURE_SUBSCRIPTION, TA_ACCESS_CODE, TA_SESSION_SECRET, and GHCR_PULL_TOKEN (a classic GitHub
#   token with read:packages only: Azure stores it to pull the private image)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

SUB="${AZURE_SUBSCRIPTION:?set AZURE_SUBSCRIPTION in .env}"
RG=rg-ticket-audit
LOC=canadacentral
ENVNAME=cae-ticket-audit
APP=ticket-audit
OWNER=$(gh api user --jq .login)
TAG=$(git rev-parse --short HEAD)
IMAGE="ghcr.io/${OWNER}/ticket-audit:${TAG}"
PULL_TOKEN="${GHCR_PULL_TOKEN:?set GHCR_PULL_TOKEN in .env (classic token, read:packages only)}"

# Guard: never deploy into any subscription but the personal one.
[ "$(az account show --subscription "$SUB" --query id -o tsv)" = "$SUB" ] || { echo "wrong subscription"; exit 1; }

if [ "${1:-}" != "--no-build" ]; then
  [ -z "$(git status --porcelain -- src assets Dockerfile pyproject.toml uv.lock)" ] || { echo "commit first: the image tag is the commit"; exit 1; }
  gh auth token | docker login ghcr.io -u "$OWNER" --password-stdin >/dev/null
  docker buildx build --platform linux/amd64 -t "$IMAGE" -t "ghcr.io/${OWNER}/ticket-audit:latest" --push .
fi

if ! az containerapp show -n "$APP" -g "$RG" --subscription "$SUB" >/dev/null 2>&1; then
  az containerapp create -n "$APP" -g "$RG" --subscription "$SUB" --environment "$ENVNAME" \
    --image "$IMAGE" --target-port 8000 --ingress external \
    --registry-server ghcr.io --registry-username "$OWNER" --registry-password "$PULL_TOKEN" \
    --cpu 0.25 --memory 0.5Gi --min-replicas 0 --max-replicas 1 \
    --secrets access-code="$TA_ACCESS_CODE" session-secret="$TA_SESSION_SECRET" \
    --env-vars ACCESS_CODE=secretref:access-code SESSION_SECRET=secretref:session-secret \
    --query properties.configuration.ingress.fqdn -o tsv
else
  az containerapp registry set -n "$APP" -g "$RG" --subscription "$SUB" \
    --server ghcr.io --username "$OWNER" --password "$PULL_TOKEN" >/dev/null
  az containerapp secret set -n "$APP" -g "$RG" --subscription "$SUB" \
    --secrets access-code="$TA_ACCESS_CODE" session-secret="$TA_SESSION_SECRET" >/dev/null
  az containerapp update -n "$APP" -g "$RG" --subscription "$SUB" --image "$IMAGE" \
    --revision-suffix "r${TAG}-$(date +%H%M%S)" --query properties.configuration.ingress.fqdn -o tsv
fi
