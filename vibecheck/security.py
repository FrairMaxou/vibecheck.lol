"""Browser-facing hardening for the localhost dashboard.

The dashboard is bound to 127.0.0.1, which stops *remote* access — and that is
where most people stop thinking about it. It isn't enough, because the browser
is a confused deputy: any page the user happens to have open can send requests
to 127.0.0.1, and they arrive looking exactly like the dashboard's own.

Three separate guards, each closing a different hole:

  TrustedHostMiddleware (wired up in dashboard.py)
      DNS rebinding. An attacker's domain resolves to 127.0.0.1, so the browser
      treats their page as same-origin with us and the same-origin policy stops
      protecting anything. Their requests still carry `Host: evil.example`,
      which is what we reject.

  require_same_site (here)
      Cross-site request forgery. The Host header is genuinely ours when a
      random page POSTs straight at http://127.0.0.1:8577 — no rebinding
      needed. The same-origin policy hides the *response* from them, but the
      side effect has already happened, and this app's side effects include
      quitting, disabling autostart and installing an update. Browsers label
      such requests (`Sec-Fetch-Site: cross-site`, or an `Origin` that isn't
      ours) and we refuse them.

  Content-Security-Policy (here)
      Cross-site scripting. The dashboard renders champion names, teammate
      names and backend error strings, and its origin can reach every endpoint
      on this list. Escaping at each render site is the real fix; the CSP is
      the net under it, and it also guarantees this page never talks to any
      host but its own.

Nothing here needs configuration and nothing degrades when a request arrives
without the headers (curl, an old browser): the guards act on positive evidence
of a cross-site caller, never on its absence.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

# Methods that cannot change state, so a cross-site *request* is harmless — the
# same-origin policy already stops the caller reading what comes back.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Fetch metadata values that mean "this did not come from another site".
# `none` covers a user typing the URL, a bookmark, or the tray opening it.
SAME_SITE_VALUES = frozenset({"same-origin", "same-site", "none"})

# script-src is the strict one: no 'unsafe-inline', so an injected <script> or
# event-handler attribute cannot run even if something slips past escaping.
# That is also why the page carries no inline handlers (see web/app.js).
# style-src has to allow inline — the tier bars set their width as a style
# attribute — which is a far smaller concession than relaxing script-src.
# connect-src 'self' means a compromised page still cannot exfiltrate anything.
CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "base-uri 'none'; "
    "form-action 'none'; "
    "frame-ancestors 'none'; "
    "object-src 'none'"
)

SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Belt and braces with frame-ancestors, for anything that predates CSP 2.
    "X-Frame-Options": "DENY",
}


def is_cross_site(request: Request) -> bool:
    """True only when the request positively identifies as coming from elsewhere.

    Checked in this order because they fail differently: `Sec-Fetch-Site` is set
    by the browser and cannot be spoofed by page script, so it is the strong
    signal; `Origin` is the fallback for anything that doesn't send fetch
    metadata. A request with neither is not treated as cross-site — that is a
    non-browser client (curl, a test), which was never the threat here.

    `Origin` is compared against the host the request itself arrived on, not a
    configured port: the dashboard's port is overridable (VIBECHECK_PORT) and
    the dev server runs on another one, so anything hardcoded here would start
    rejecting the app's own page the moment it moved. The host is safe to trust
    as the comparison anchor because TrustedHostMiddleware has already
    established it is ours.

    Do not "tighten" this into requiring positive proof of same-origin. The
    absent-headers case is load-bearing: window.py runs in its own process and
    POSTs /api/quit through urllib when the user closes the window with the X,
    sending neither header. Demanding them would break that, and would buy
    nothing — a caller able to set arbitrary headers is a local program, which
    can read the SQLite file directly anyway. The threat is the browser.
    """
    site = request.headers.get("sec-fetch-site")
    if site:
        return site not in SAME_SITE_VALUES
    origin = request.headers.get("origin")
    if not origin:
        return False
    host = request.headers.get("host", "")
    return origin not in {f"http://{host}", f"https://{host}"}


def add_security_guards(app: FastAPI) -> None:
    """Attach the CSRF guard and the response security headers."""

    @app.middleware("http")
    async def _guard(request: Request, call_next):
        if request.method not in SAFE_METHODS and is_cross_site(request):
            # 403 with no detail: the caller is another site and must learn
            # nothing about what lives here.
            return JSONResponse({"detail": "cross-site request rejected"}, status_code=403)
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response
