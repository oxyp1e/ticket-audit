"""The deployed system: runs the audit on the preloaded batches at startup, then serves the reports
behind an access code. Read-only: no uploads, no Azure key. OCR results come from the saved Azure
responses shipped with each batch, with a page budget of zero, so this process can never spend pages.

    ACCESS_CODE=... SESSION_SECRET=... uv run uvicorn ticket_audit.web:app
"""
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

from ticket_audit.evaluate import field_accuracy, outcomes
from ticket_audit.extract.azure import AzureExtractor
from ticket_audit.extract.truth import TruthExtractor
from ticket_audit.pipeline import run_batch
from ticket_audit.report import render, summarize

log = logging.getLogger("ticket_audit.web")
DATA = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "generated"))
COOKIE = "ta_session"
SESSION_HOURS = 12
FILE_NAME = re.compile(r"^IMG_\d{4}\.jpg$")
BATCH_NAME = re.compile(r"^[a-z0-9-]{1,32}$")
LOGIN_ATTEMPTS = 5          # per IP per window
LOGIN_WINDOW_S = 15 * 60

STATE: dict = {"batches": {}, "ready": False, "error": None}
_attempts: dict[str, deque] = defaultdict(deque)


# ── Startup: audit every preloaded batch ─────────────────────────────────────
def audit_all() -> None:
    import json
    for batch in sorted(p for p in DATA.iterdir() if (p / "tms.sqlite").exists()):
        raw = batch / "out" / "azure" / "raw"
        if raw.is_dir():
            # Cache-only: no endpoint, no key, zero page budget. A missing response fails the batch closed.
            extractor, engine = AzureExtractor("https://cache-only.invalid/", "", raw_dir=raw, max_pages=0), "azure"
        else:
            extractor, engine = TruthExtractor(batch / "truth" / "documents.json"), "truth"
        t0 = time.perf_counter()
        summary = run_batch(batch, extractor)
        evaluation = {"fields": field_accuracy(batch, engine), "outcomes": outcomes(batch, engine)}
        (batch / "out" / engine / "evaluation.json").write_text(json.dumps(evaluation, indent=1))
        STATE["batches"][batch.name] = {"engine": engine, "summary": summarize(batch, engine)}
        log.info("audited %s with %s in %.2fs: %s approved, %s held",
                 batch.name, engine, time.perf_counter() - t0, summary.approved + summary.approved_adjusted,
                 summary.exceptions + summary.missing_tickets)
    STATE["ready"] = True


@asynccontextmanager
async def lifespan(app):
    try:
        audit_all()
    except Exception as exc:  # fail closed: serve nothing rather than a partial audit
        STATE["error"] = repr(exc)
        log.exception("startup audit failed")
    yield


# ── Access code ──────────────────────────────────────────────────────────────
def _secret() -> bytes:
    return os.environ.get("SESSION_SECRET", "").encode()


def _token(expires: int) -> str:
    sig = hmac.new(_secret(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def _valid(token: str | None) -> bool:
    if not token or "." not in token or not _secret():
        return False
    expires, _ = token.split(".", 1)
    return expires.isdigit() and int(expires) > time.time() and hmac.compare_digest(token, _token(int(expires)))


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


class Guard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path not in ("/login", "/healthz") and not _valid(request.cookies.get(COOKIE)):
            return RedirectResponse("/login", status_code=303)
        response = await call_next(request)
        response.headers.update({
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; "
                                       "form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
            "X-Robots-Tag": "noindex, nofollow",
            "Cache-Control": "private, no-store" if response.headers.get("content-type", "").startswith("text/html")
                             else "private, max-age=3600",
        })
        return response


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Ticket Audit</title>
<style>
:root {{ --bg:#f6f5f1; --panel:#fff; --ink:#1d1d1f; --muted:#6b6b70; --line:#e4e2dc; --accent:#1f5f8b; --warn:#a15c00; --on-warn:#fff; --bad:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#141416; --panel:#1d1d20; --ink:#ececee; --muted:#9a9aa1; --line:#2e2e33; --accent:#78b3dc; --warn:#e5a44a; --on-warn:#1d1d1f; --bad:#f28b82; }} }}
:root[data-theme="dark"] {{ --bg:#141416; --panel:#1d1d20; --ink:#ececee; --muted:#9a9aa1; --line:#2e2e33; --accent:#78b3dc; --warn:#e5a44a; --on-warn:#1d1d1f; --bad:#f28b82; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width:720px; margin:0 auto; padding:48px 16px; }}
h1 {{ font-size:24px; margin:0 0 4px; }} p {{ color:var(--muted); }}
.synthetic {{ display:inline-block; background:var(--warn); color:var(--on-warn); font-size:12px; font-weight:600; padding:2px 8px; border-radius:99px; }}
.card {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px 20px; margin-top:16px; display:block; color:inherit; text-decoration:none; }}
a.card:hover {{ border-color:var(--accent); }}
.card b {{ font-size:17px; }} .row {{ display:flex; gap:20px; flex-wrap:wrap; margin-top:6px; font-size:14px; color:var(--muted); }}
form {{ display:flex; gap:8px; margin-top:20px; flex-wrap:wrap; }}
input {{ flex:1; min-width:200px; font:inherit; padding:10px 12px; border:1px solid var(--line); border-radius:8px; background:var(--panel); color:var(--ink); }}
button {{ font:inherit; font-weight:600; padding:10px 18px; border:0; border-radius:8px; background:var(--accent); color:#fff; cursor:pointer; }}
.err {{ color:var(--bad); }} a {{ color:var(--accent); }}
</style></head><body><main>{body}</main></body></html>"""


async def login(request: Request) -> Response:
    error = ""
    if request.method == "POST":
        ip, now = _client(request), time.time()
        window = _attempts[ip]
        while window and window[0] < now - LOGIN_WINDOW_S:
            window.popleft()
        if len(window) >= LOGIN_ATTEMPTS:
            return HTMLResponse(PAGE.format(body="<h1>Ticket Audit</h1><p class='err'>Too many attempts. "
                                                 "Try again in 15 minutes.</p>"), status_code=429)
        code = (await request.form()).get("code", "")
        expected = os.environ.get("ACCESS_CODE", "")
        if expected and hmac.compare_digest(str(code).strip().encode(), expected.encode()):
            window.clear()
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(COOKIE, _token(int(now) + SESSION_HOURS * 3600), max_age=SESSION_HOURS * 3600,
                                httponly=True, secure=request.url.scheme == "https" or
                                request.headers.get("x-forwarded-proto") == "https", samesite="strict")
            return response
        window.append(now)
        error = "<p class='err'>That code didn't work.</p>"
    body = f"""<h1>Ticket Audit</h1><span class="synthetic">Synthetic data only</span>
<p>Reads haul and scale tickets, matches them to dispatch and rates, and holds anything uncertain for a person.
Every company, ticket and rate here is invented.</p>
<form method="post"><input name="code" type="password" placeholder="Access code" autocomplete="current-password"
autofocus required><button type="submit">Open</button></form>{error}"""
    return HTMLResponse(PAGE.format(body=body))


async def logout(request: Request) -> Response:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE)
    return response


def _not_ready() -> Response:
    if STATE["error"]:
        return HTMLResponse(PAGE.format(body="<h1>Ticket Audit</h1><p class='err'>The startup audit failed, so "
                                             "nothing is shown. See the runbook.</p>"), status_code=503)
    return HTMLResponse(PAGE.format(body="<h1>Ticket Audit</h1><p>Auditing the batches. Refresh in a few "
                                         "seconds.</p>"), status_code=503, headers={"Retry-After": "5"})


async def index(request: Request) -> Response:
    if not STATE["ready"]:
        return _not_ready()
    cards = ""
    for name, b in STATE["batches"].items():
        s = b["summary"]
        days = s.days[0] if len(s.days) == 1 else f"{s.days[0]} – {s.days[-1]}"
        cards += f"""<a class="card" href="/b/{escape(name)}/"><b>{escape(name.capitalize())} batch</b>
<span class="row"><span>{escape(days)}</span><span>{s.tickets} tickets</span><span>touchless {s.touchless:.0%}</span>
<span>underbilling found ${s.underbilling:,.2f}</span><span>overbilling prevented ${s.overbilling_prevented:,.2f}</span></span></a>"""
    body = f"""<h1>Ticket Audit</h1><span class="synthetic">Synthetic data only</span>
<p>Each batch was audited when this server started: photos read by Azure AI Document Intelligence (saved responses),
matched to dispatch and rates, and decided by the rules.</p>{cards}
<p style="margin-top:28px"><a href="/logout">Sign out</a></p>"""
    return HTMLResponse(PAGE.format(body=body))


def _batch(request: Request):
    name = request.path_params["batch"]
    if not BATCH_NAME.match(name) or name not in STATE["batches"]:
        return None, None
    return name, STATE["batches"][name]


async def report(request: Request) -> Response:
    if not STATE["ready"]:
        return _not_ready()
    name, b = _batch(request)
    if b is None:
        return PlainTextResponse("Not found", status_code=404)
    html = render(b["summary"], batch_rel=".")
    html = html.replace("<main>", '<main><p style="margin:0 0 12px"><a href="/">← All batches</a></p>', 1)
    return HTMLResponse(html)


async def photo(request: Request) -> Response:
    name, b = _batch(request)
    file = request.path_params["file"]
    if b is None or not FILE_NAME.match(file):
        return PlainTextResponse("Not found", status_code=404)
    path = DATA / name / "inbox" / file
    return FileResponse(path, media_type="image/jpeg") if path.is_file() else PlainTextResponse("Not found", 404)


async def download(request: Request) -> Response:
    name, b = _batch(request)
    file = request.path_params["file"]
    if b is None or file not in ("approved.csv", "exceptions.csv"):
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(DATA / name / "out" / b["engine"] / file, media_type="text/csv", filename=f"{name}-{file}")


async def healthz(request: Request) -> Response:
    if STATE["error"]:
        return PlainTextResponse("startup audit failed", status_code=503)
    return PlainTextResponse("ok" if STATE["ready"] else "starting", status_code=200 if STATE["ready"] else 503)


def _check_config() -> None:
    if len(os.environ.get("ACCESS_CODE", "")) < 8 or len(os.environ.get("SESSION_SECRET", "")) < 32:
        log.warning("ACCESS_CODE (>= 8 chars) and SESSION_SECRET (>= 32 chars) must be set; nobody can sign in")


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
_check_config()
app = Starlette(
    routes=[
        Route("/", index), Route("/login", login, methods=["GET", "POST"]), Route("/logout", logout),
        Route("/healthz", healthz), Route("/b/{batch}/", report), Route("/b/{batch}/inbox/{file}", photo),
        Route("/b/{batch}/{file}", download),
    ],
    middleware=[Middleware(Guard)],
    lifespan=lifespan,
)


if __name__ == "__main__":
    print(secrets.token_urlsafe(32))  # handy for generating SESSION_SECRET
