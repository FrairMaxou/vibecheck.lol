"""Guards the dashboard's browser-facing hardening (vibecheck/security.py).

Run: .venv\\Scripts\\python tests\\security_test.py

Every check here failed before the hardening landed, which is the only reason
any of them are worth running. They exist because all three holes are invisible
in normal use — the app looks and behaves identically with the guards removed,
so nothing but a test would notice a regression.
"""

import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from vibecheck.dashboard import create_app
from vibecheck.store import GameStore

# Endpoints that change state and take no request body — the CSRF-reachable set.
# A body would force a JSON content-type, which needs a CORS preflight the
# browser will not grant; with no body a plain cross-site form POST goes
# straight through, so these are the ones the guard actually has to stop.
BODYLESS_WRITES = [
    "/api/quit",
    "/api/uninstall",
    "/api/update/install",
    "/api/onboarding/seen",
    "/api/whats-new/seen",
    "/api/squad/push",
]

CROSS_SITE = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
SAME_SITE = {"Origin": "http://127.0.0.1", "Sec-Fetch-Site": "same-origin"}


def client() -> TestClient:
    tmp = Path(tempfile.mkdtemp()) / "test.sqlite3"
    # base_url matters: TrustedHostMiddleware rejects TestClient's default
    # `testserver` Host outright, which would turn every assertion below into a
    # 400 and quietly stop testing the thing it names.
    # raise_server_exceptions=False: we assert on status codes, and a handler
    # blowing up should show as a 500 here rather than as a test error.
    return TestClient(
        create_app(GameStore(tmp)),
        base_url="http://127.0.0.1",
        raise_server_exceptions=False,
    )


def check_untrusted_host_rejected():
    """DNS rebinding: an attacker domain pointed at 127.0.0.1 still says so."""
    c = client()
    assert c.get("/api/games", headers={"Host": "evil.example"}).status_code == 400


def check_cross_site_writes_rejected():
    """A page on any other origin must not be able to trigger a state change."""
    c = client()
    for path in BODYLESS_WRITES:
        resp = c.post(path, headers=CROSS_SITE)
        assert resp.status_code == 403, f"{path} accepted a cross-site POST ({resp.status_code})"
    # Sec-Fetch-Site alone is enough — browsers send it and page script can't
    # forge it, so a request carrying no Origin is still caught.
    assert c.post("/api/quit", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403


def check_same_site_writes_allowed():
    """The dashboard's own page must keep working, on whatever port it's on."""
    c = client()
    assert c.post("/api/whats-new/seen", headers=SAME_SITE).status_code == 200
    # Typed in the address bar / opened from the tray: no Origin, site "none".
    assert c.post("/api/whats-new/seen", headers={"Sec-Fetch-Site": "none"}).status_code == 200
    # A non-browser client sends neither header and is not what the guard
    # defends against, so it must not be locked out. This is not hypothetical:
    # window.py POSTs /api/quit through urllib from its own process when the
    # user closes the window with the X. Tightening the guard breaks that.
    assert c.post("/api/quit").status_code == 200


def check_reads_are_not_blocked():
    """GET can't change anything, and the same-origin policy hides the body."""
    c = client()
    assert c.get("/api/games", headers=CROSS_SITE).status_code == 200


def check_security_headers():
    """Every response carries the CSP, on error paths too."""
    for resp in (client().get("/api/games"), client().get("/static/nope.js")):
        csp = resp.headers.get("content-security-policy", "")
        assert "script-src 'self'" in csp, f"CSP missing or too loose: {csp!r}"
        # The whole point of the strict script-src: an injected inline handler
        # or <script> must not run even if escaping is bypassed somewhere.
        assert "'unsafe-inline'" not in csp.split("style-src")[0], f"script-src is inline: {csp!r}"
        assert resp.headers.get("x-content-type-options") == "nosniff"


def check_no_inline_handlers_in_page():
    """Inline handlers would silently stop working under that CSP.

    Cheaper to catch here than to notice a champion icon that no longer hides
    itself, months later.
    """
    web = Path(__file__).resolve().parent.parent / "vibecheck" / "web"
    for name in ("index.html", "app.js"):
        text = (web / name).read_text(encoding="utf-8")
        for handler in ("onerror=", "onclick=", "onload=", "onchange="):
            assert handler not in text, f"{name} has an inline {handler} — the CSP blocks it"


def check_frontend_posts_to_post_routes():
    """Every POST-only endpoint must be called by app.js with a body.

    `api(path, body)` picks its method from whether a body was passed, so
    `api("/api/squad/push")` silently sends a GET and the route answers 405.
    That is how the Sync now button shipped broken and stayed broken: the
    failure is one line of orange text in a corner of the UI, and the automatic
    background sync covered for it.

    Lives here because it is the same shape as the CSP check below — a contract
    between the page and the server that nothing else in CI would notice.
    """
    root = Path(__file__).resolve().parent.parent
    dashboard = (root / "vibecheck" / "dashboard.py").read_text(encoding="utf-8")
    app_js = (root / "vibecheck" / "web" / "app.js").read_text(encoding="utf-8")

    posts = set(re.findall(r'@app\.post\("([^"{]+)"\)', dashboard))
    gets = set(re.findall(r'@app\.get\("([^"{]+)"\)', dashboard))
    assert posts, "found no POST routes - the regex stopped matching"
    # A path serving both verbs (/api/settings) is fine to call bodyless: that
    # request is meant to be the GET. Only POST-only paths are the trap.
    for route in sorted(posts - gets):
        assert f'api("{route}")' not in app_js, (
            f'app.js calls api("{route}") with no body - that sends GET to a '
            f"POST-only route and 405s. Pass {{}} as the body."
        )


def check_docs_are_not_served():
    """FastAPI's interactive docs enumerate every endpoint; they stay off."""
    c = client()
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert c.get(path).status_code == 404, f"{path} is exposed"


def check_static_allowlist():
    """No reading arbitrary files off disk through the asset routes."""
    c = client()
    for path in ("/static/../config.py", "/static/secrets.txt", "/assets/../../store.py"):
        assert c.get(path).status_code == 404, f"{path} was served"


def check_input_bounds():
    """Oversized input is bounded rather than written to the database as-is."""
    c = client()
    note = c.post("/api/games/1/note", json={"note": "x" * 5000}, headers=SAME_SITE)
    assert note.status_code == 422, f"oversized note accepted ({note.status_code})"
    assert c.post("/api/games/1/rating", json={"score": 99}, headers=SAME_SITE).status_code == 422
    # A backend URL decides where every rated game is sent; it must be http(s).
    bad_url = {"url": "javascript:alert(1)", "anon_key": "k"}
    assert c.post("/api/squad/config", json=bad_url, headers=SAME_SITE).status_code == 422


def main():
    checks = [v for k, v in sorted(globals().items()) if k.startswith("check_")]
    for check in checks:
        check()
        print(f"  ok  {check.__name__}")
    print(f"\nSecurity checks passed ({len(checks)})")


if __name__ == "__main__":
    main()
