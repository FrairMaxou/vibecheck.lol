"""Native desktop window for the dashboard (PRD §14, Blitz/u.gg-style).

Runs as its OWN process on purpose: pywebview must own its process's main
thread, and the tray app's main thread already belongs to Tk (the rating
popup). Launching on demand also means the window costs nothing while closed,
which keeps the resident tray process within the §6b footprint.

Uses the OS Edge WebView2 runtime — no bundled browser. Falls back to the
default browser if a webview can't be created, so "Open dashboard" always
does something.

Closing the window (the X) consults the user's "close_action" setting, served
by the tray process's dashboard API:
  * "minimize" — just close the window; the app keeps running in the tray
  * "quit"     — ask the tray process to shut the whole app down
  * "ask"      — prompt (default): OK quits, Cancel keeps it in the tray

Run: python -m vibecheck.window [url]
"""

import json
import logging
import sys
import urllib.request
import webbrowser

from .config import APP_NAME, DASHBOARD_HOST, DASHBOARD_PORT

log = logging.getLogger(__name__)

BG = "#10141a"  # matches the dashboard page background, so no white flash


def _api(url: str, path: str, method: str = "GET"):
    """Call the tray process's local dashboard API (127.0.0.1 only)."""
    req = urllib.request.Request(url.rstrip("/") + path, method=method)  # noqa: S310 - fixed localhost URL
    with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310 - fixed localhost URL
        return json.load(resp) if method == "GET" else None


def _close_action(url: str) -> str:
    try:
        return (_api(url, "/api/settings") or {}).get("close_action", "ask")
    except Exception:
        return "ask"  # a hiccup should never trap the user's window open


def open_window(url: str) -> None:
    """Open the dashboard in a native window; fall back to the browser."""
    try:
        import webview

        win = webview.create_window(
            APP_NAME,
            url,
            width=1360,
            height=900,
            min_size=(900, 600),
            background_color=BG,
        )

        def on_closing():
            action = _close_action(url)
            quit_app = action == "quit"
            if action == "ask":
                quit_app = win.create_confirmation_dialog(
                    APP_NAME,
                    "Quit VibeCheck completely?\n\n"
                    "Choose Cancel to keep it running in your system tray.",
                )
            if quit_app:
                try:
                    _api(url, "/api/quit", method="POST")
                except Exception:
                    log.warning("Quit request failed", exc_info=True)
            return True  # always let the window itself close

        win.events.closing += on_closing
        webview.start()
    except Exception:
        log.exception("Native window unavailable; opening the browser instead")
        webbrowser.open(url)


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
    open_window(url)


if __name__ == "__main__":
    main()
