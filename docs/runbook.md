# Runbook

What to do when something fails. The rule throughout: **fail closed**. A failure may delay tickets; it must never approve one.

## At a glance

| Symptom | What the system already does | What you do |
|---|---|---|
| Azure Document Intelligence throttles (HTTP 429) | Waits (Retry-After, capped at 15 s) and retries, up to 8 times | Nothing. The free tier allows about 5 photos a minute |
| Network drop / timeout mid-run | Retries with backoff; if it still fails, the run is marked `failed` | Run the same command again: saved results are reused, nothing is read twice |
| Page budget reached (`PageBudgetExceeded`) | Stops before sending more pages; everything read so far is cached | Check the month's usage (below), then re-run with a higher `--max-pages` or wait for the monthly reset |
| Azure returns an error for one document | The run fails; nothing is approved; cached results are kept | Look at the document; re-run. A document Azure can't read at all becomes `UNREADABLE_DOCUMENT` |
| OCR misreads a value | Cross-checks hold it (scale ticket, dispatch, master data) or the confidence floor does | Work it in the exception queue like any other item |
| Run store lost or corrupted (`store.sqlite`) | — | Delete `out/<engine>/store.sqlite` and re-run. Extractions rebuild from the saved responses in `out/azure/raw/` at no cost; the decision log restarts |
| Saved responses lost (`out/azure/raw/`) | — | They cost free-tier pages to rebuild (about 260 for both batches). Never delete them; back them up with the batch |
| Deployed app shows "startup audit failed" (HTTP 503) | Serves nothing rather than a partial audit | Read the container logs (below). Usually a missing saved response: the image was built without `out/azure/raw` |
| Budget alert email | Free Trial spending limit blocks real charges | Find the resource in Cost Management; scale the app to zero or delete it |

## Commands

```bash
# Audit a batch (generator truth: no OCR, no cost)
uv run python -m ticket_audit data/generated/day

# Audit with Azure; stops before sending more than --max-pages new pages
uv run python -m ticket_audit data/generated/day --engine azure --max-pages 200

# Re-apply a changed mapping or rules to saved responses only: guaranteed zero pages
uv run python -m ticket_audit data/generated/day --engine azure --max-pages 0

# Compare a run with the answer key (synthetic batches only)
uv run python -m ticket_audit.evaluate data/generated/day --engine azure

# All checks, including the three fitness functions
uv run pytest
```

## Deployment (Azure Container Apps)

Personal subscription only; every command names it explicitly. Resources live in `rg-ticket-audit` (Canada Central): Document Intelligence `di-ticket-audit-vapo` (F0), Log Analytics `law-ticket-audit` (0.1 GB/day cap), environment `cae-ticket-audit`, app `ticket-audit`. Budget `budget-1-usd` emails at 50% and 100% of $1.

```bash
deploy/deploy.sh             # commit first: build, push to ghcr.io, deploy a new revision
deploy/deploy.sh --no-build  # redeploy the current image, e.g. after rotating the access code
```

**Image pull token:** the image on ghcr.io is private; Azure pulls it with `GHCR_PULL_TOKEN`, a classic GitHub token with `read:packages` only (90-day expiry). When it expires, new revisions fail to start with `UNAUTHORIZED`: create a new token, update `.env`, run `deploy/deploy.sh --no-build`.

**Rotate the access code:** change `TA_ACCESS_CODE` in `.env`, run `deploy/deploy.sh --no-build`. To sign everyone out as well, also change `TA_SESSION_SECRET`.

**Logs:**
```bash
az containerapp logs show -n ticket-audit -g rg-ticket-audit --subscription "$AZURE_SUBSCRIPTION" --tail 100
```
A healthy start logs one line per batch: `audited day with azure in 1.0s: 89 approved, 12 held`.

**Keeping it warm for a review window:** the app normally scales to zero, so the first visit after a quiet spell takes about 30 s (the container starts and re-audits both batches). For a review window, keep one replica: `az containerapp update -n ticket-audit -g rg-ticket-audit --subscription "$AZURE_SUBSCRIPTION" --min-replicas 1`. The scheduled job `job-scale-to-zero` (Azure CLI image, its own managed identity with Contributor on this app only) sets it back to zero at its cron time; run it early with `az containerapp job start -n job-scale-to-zero -g rg-ticket-audit --subscription "$AZURE_SUBSCRIPTION"`. Its cron fires yearly, so delete the job once it has done its work.

**Kill switch:**
```bash
# Take it offline (keeps everything for later)
az containerapp ingress disable -n ticket-audit -g rg-ticket-audit --subscription "$AZURE_SUBSCRIPTION"
# Remove everything, including the OCR resource
az group delete -n rg-ticket-audit --subscription "$AZURE_SUBSCRIPTION"
```

## Free-tier facts

- Document Intelligence F0: 500 pages a month; refuses beyond that rather than billing. Throughput ≈ 5 photos a minute (each photo is one upload plus status checks against the per-minute limit).
- Container Apps consumption: 180,000 vCPU-seconds and 360,000 GiB-seconds free a month. At 0.25 vCPU that is 200 hours of activity; the app scales to zero when idle.
- Log Analytics: first 5 GB a month free; the workspace is capped at 0.1 GB a day.
- The subscription is a 30-day Free Trial (to about 2026-11-05). Keeping the system running after that requires moving to pay-as-you-go; at this usage it stays at $0, but it is a decision to make, not a default.

**Pages used so far:** about 280 in October 2026 (both batches read once, plus probes).
