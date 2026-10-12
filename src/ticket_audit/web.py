"""The deployed system: runs the audit on the preloaded batches at startup, then serves the reports
behind an access code. Read-only: no uploads, no Azure key. OCR results come from the saved Azure
responses shipped with each batch, with a page budget of zero, so this process can never spend pages.

    ACCESS_CODE=... SESSION_SECRET=... uv run uvicorn ticket_audit.web:app
"""
import hashlib
import json
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
from ticket_audit.report import summarize
from ticket_audit.site import dashboard_page, home, lines_page, queue_page, rules_page, trace_page

log = logging.getLogger("ticket_audit.web")
DATA = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parents[2] / "data" / "generated"))
COOKIE = "ta_session"
SESSION_HOURS = 12
FILE_NAME = re.compile(r"^IMG_\d{4}\.jpg$")
SUBJECT = re.compile(r"^(IMG_\d{4}\.jpg|D-\d{2}-\d{4})$")
STATIC = Path(__file__).resolve().parents[2] / "assets" / "web"
STATIC_FILES = {"Inter.woff2": "font/woff2", "favicon.svg": "image/svg+xml"}
BUILD_INFO = Path(os.environ.get("BUILD_INFO", Path(__file__).resolve().parents[2] / "build-info.json"))
BATCH_NAME = re.compile(r"^[a-z0-9-]{1,32}$")
LOGIN_ATTEMPTS = 5          # per IP per window
LOGIN_WINDOW_S = 15 * 60

STATE: dict = {"batches": {}, "ready": False, "error": None, "timings": {}, "build": None}
_attempts: dict[str, deque] = defaultdict(deque)


# ── Startup: audit every preloaded batch ─────────────────────────────────────
def audit_all() -> None:

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
        STATE["timings"][batch.name] = time.perf_counter() - t0
        log.info("audited %s with %s in %.2fs: %s approved, %s held",
                 batch.name, engine, time.perf_counter() - t0, summary.approved + summary.approved_adjusted,
                 summary.exceptions + summary.missing_tickets)
    if BUILD_INFO.exists():
        STATE["build"] = json.loads(BUILD_INFO.read_text())
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
        public = request.url.path in ("/login", "/healthz") or request.url.path.startswith("/static/")
        if not public and not _valid(request.cookies.get(COOKIE)):
            return RedirectResponse("/login", status_code=303)
        response = await call_next(request)
        response.headers.update({
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; font-src 'self'; "
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
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
<style>
@font-face {{ font-family:"Inter"; src:url("/static/Inter.woff2") format("woff2"); font-weight:100 900; font-display:swap; }}
:root {{ --bg:#0f1b2a; --panel:#fff; --ink:#18202b; --muted:#5f6b7a; --line:#e3e6ea; --accent:#1d5f8f; --warn:#965a00; --bad:#b42318; }}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{ --bg:#0a0d12; --panel:#171a20; --ink:#e8ebef; --muted:#99a3af; --line:#2a2f37; --accent:#7cb4df; --warn:#e5a44a; --bad:#f28b82; }} }}
:root[data-theme="dark"] {{ --bg:#0a0d12; --panel:#171a20; --ink:#e8ebef; --muted:#99a3af; --line:#2a2f37; --accent:#7cb4df; --warn:#e5a44a; --bad:#f28b82; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; min-height:100vh; display:grid; place-items:center; padding:24px 16px; background:var(--bg);
  background-image:radial-gradient(1200px 500px at 20% -10%, rgba(43,123,185,.35), transparent 60%);
  color:var(--ink); font:15px/1.55 Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
main {{ width:100%; max-width:440px; background:var(--panel); border-radius:16px; padding:30px 28px; box-shadow:0 20px 60px rgba(0,0,0,.35); }}
.brand {{ display:flex; align-items:center; gap:10px; font-weight:700; font-size:17px; margin-bottom:18px; }}
h1 {{ font-size:22px; line-height:1.25; margin:0 0 8px; letter-spacing:-.01em; }} p {{ color:var(--muted); margin:0 0 12px; }}
.synthetic {{ display:inline-flex; align-items:center; gap:6px; font-size:12px; font-weight:600; color:var(--warn); }}
.synthetic::before {{ content:""; width:7px; height:7px; border-radius:50%; background:currentColor; }}
form {{ display:flex; flex-direction:column; gap:10px; margin-top:18px; }}
label {{ font-size:13px; font-weight:600; }}
input {{ font:inherit; padding:11px 12px; border:1px solid var(--line); border-radius:9px; background:transparent; color:var(--ink); }}
input:focus {{ outline:2px solid var(--accent); outline-offset:1px; border-color:transparent; }}
button {{ font:inherit; font-weight:600; padding:11px 18px; border:0; border-radius:9px; background:var(--accent); color:#fff; cursor:pointer; }}
.err {{ color:var(--bad); margin-top:10px; }} a {{ color:var(--accent); }}
.foot {{ margin-top:18px; padding-top:14px; border-top:1px solid var(--line); font-size:12.5px; color:var(--muted); }}
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
    body = f"""<div class="brand"><svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true"><rect width="26" height="26" rx="7" fill="#2b7bb9"/><path d="M7 7h12v12H7z" fill="none" stroke="#fff" stroke-width="1.6" stroke-dasharray="2.2 1.6"/><path d="M9.5 13.2l2.3 2.3 4.7-5" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>Ticket Audit</div>
<h1>Automated ticket audit before invoicing</h1>
<p>Reads haul and scale tickets, compares them with dispatch and the rate sheet, and holds anything uncertain for a
person with a plain reason.</p><span class="synthetic">Synthetic data only: every company, ticket and rate is invented</span>
<form method="post"><label for="code">Access code</label><input id="code" name="code" type="password"
autocomplete="current-password" autofocus required><button type="submit">Sign in</button></form>{error}
<div class="foot">Read-only. Built and deployed by Vitalii Apostolyuk.</div>"""
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
    return HTMLResponse(home(STATE))


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
    return HTMLResponse(dashboard_page(name, STATE))


async def queue(request: Request) -> Response:
    if not STATE["ready"]:
        return _not_ready()
    name, b = _batch(request)
    if b is None:
        return PlainTextResponse("Not found", status_code=404)
    p = request.query_params
    return HTMLResponse(queue_page(name, STATE, reason=p.get("reason", "")[:40], source=p.get("source", "")[:10],
                                   q=p.get("q", "")[:40]))


async def lines(request: Request) -> Response:
    if not STATE["ready"]:
        return _not_ready()
    name, b = _batch(request)
    if b is None:
        return PlainTextResponse("Not found", status_code=404)
    return HTMLResponse(lines_page(name, STATE))


async def rules(request: Request) -> Response:
    if not STATE["ready"]:
        return _not_ready()
    return HTMLResponse(rules_page(STATE))


async def static(request: Request) -> Response:
    file = request.path_params["file"]
    if file not in STATIC_FILES:
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(STATIC / file, media_type=STATIC_FILES[file], headers={"Cache-Control": "public, max-age=86400"})


async def trace(request: Request) -> Response:
    if not STATE["ready"]:
        return _not_ready()
    name, b = _batch(request)
    subject = request.path_params["subject"]
    if b is None or not SUBJECT.match(subject) or subject not in b["summary"].entries:
        return PlainTextResponse("Not found", status_code=404)
    return HTMLResponse(trace_page(name, b["summary"].entries[subject], STATE))


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
        Route("/healthz", healthz), Route("/rules", rules), Route("/static/{file}", static),
        Route("/b/{batch}/", report), Route("/b/{batch}/queue", queue), Route("/b/{batch}/lines", lines),
        Route("/b/{batch}/t/{subject}", trace),
        Route("/b/{batch}/inbox/{file}", photo),
        Route("/b/{batch}/{file}", download),
    ],
    middleware=[Middleware(Guard)],
    lifespan=lifespan,
)


if __name__ == "__main__":
    print(secrets.token_urlsafe(32))  # handy for generating SESSION_SECRET
