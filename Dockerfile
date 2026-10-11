# The deployed system: audits the preloaded synthetic batches at startup and serves the site.
# No Azure key inside: OCR results come from the saved responses shipped under out/azure/raw.
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./

# Test stage: the full suite plus deliberate breaks. The build stops here if anything fails,
# and the results become build-info.json, shown on the site.
FROM base AS test
ARG GIT_SHA=unknown
RUN uv sync --frozen --no-install-project
COPY src ./src
COPY assets ./assets
COPY tests ./tests
COPY scripts ./scripts
RUN uv sync --frozen && uv run python scripts/build_info.py --commit "$GIT_SHA" --out /build-info.json

FROM base AS runtime
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY assets ./assets
RUN uv sync --frozen --no-dev
COPY --from=test /build-info.json /app/build-info.json
COPY data/generated ./data/generated
RUN useradd --system --uid 10001 app && chown -R app /app/data
USER app
ENV DATA_DIR=/app/data/generated BUILD_INFO=/app/build-info.json
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"
CMD ["/app/.venv/bin/uvicorn", "ticket_audit.web:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
