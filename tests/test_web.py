"""The deployed app: nothing without the access code, nothing outside the batch folders."""
import importlib
import shutil

import pytest
from starlette.testclient import TestClient

from tests.test_fitness import make_batch


@pytest.fixture(scope="module")
def client(tmp_path_factory, monkeypatch_module):
    data = tmp_path_factory.mktemp("web")
    make_batch(data, "audit")
    monkeypatch_module.setenv("DATA_DIR", str(data))
    monkeypatch_module.setenv("ACCESS_CODE", "right-code-123")
    monkeypatch_module.setenv("SESSION_SECRET", "s" * 40)
    import ticket_audit.web as web
    web = importlib.reload(web)
    with TestClient(web.app, base_url="https://testserver") as c:
        yield c, data


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def test_everything_needs_the_access_code(client):
    c, _ = client
    c.cookies.clear()
    for path in ("/", "/b/audit/", "/b/audit/approved.csv"):
        r = c.get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/healthz").text == "ok"


def test_forged_cookie_is_rejected(client):
    c, _ = client
    c.cookies.clear()
    c.cookies.set("ta_session", "9999999999.deadbeef")
    assert c.get("/", follow_redirects=False).status_code == 303
    c.cookies.clear()


def test_right_code_opens_the_reports_and_photos(client):
    c, data = client
    c.cookies.clear()
    r = c.post("/login", data={"code": "right-code-123"}, follow_redirects=False)
    assert r.status_code == 303 and "httponly" in r.headers["set-cookie"].lower()
    page = c.get("/b/audit/")
    assert page.status_code == 200 and "Synthetic batch" in page.text
    assert page.headers["cache-control"] == "private, no-store"
    photo = sorted((data / "audit" / "inbox").iterdir())[0].name
    assert c.get(f"/b/audit/inbox/{photo}").status_code == 200
    assert c.get("/b/audit/exceptions.csv").status_code == 200


def test_nothing_outside_the_batch_folders(client):
    c, _ = client
    c.post("/login", data={"code": "right-code-123"})
    for path in ("/b/audit/inbox/..%2Ftms.sqlite", "/b/audit/tms.sqlite", "/b/audit/truth",
                 "/b/..%2F..%2Fetc/inbox/IMG_1234.jpg", "/b/nope/"):
        assert c.get(path).status_code == 404, path


def test_sign_in_attempts_are_limited(client):
    c, _ = client
    c.cookies.clear()
    codes = [c.post("/login", data={"code": "wrong"}, headers={"x-forwarded-for": "203.0.113.9"}).status_code
             for _ in range(6)]
    assert codes[-1] == 429 and codes[0] == 200
