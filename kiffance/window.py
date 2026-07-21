"""Native desktop window for the dashboard (PRD §14, Blitz/u.gg-style).

Runs as its OWN process on purpose: pywebview must own its process's main
thread, and the tray app's main thread already belongs to Tk (the rating
popup). Launching on demand also means the window costs nothing while closed,
which keeps the resident tray process within the §6b footprint.

Uses the OS Edge WebView2 runtime — no bundled browser. Falls back to the
default browser if a webview can't be created, so "Open dashboard" always
does something.

Run: python -m kiffance.window [url]
"""

import logging
import sys
import webbrowser

from .config import APP_NAME, DASHBOARD_HOST, DASHBOARD_PORT

log = logging.getLogger(__name__)

BG = "#10141a"  # matches the dashboard page background, so no white flash


def open_window(url: str) -> None:
    """Open the dashboard in a native window; fall back to the browser."""
    try:
        import webview

        webview.create_window(
            APP_NAME,
            url,
            width=1360,
            height=900,
            min_size=(900, 600),
            background_color=BG,
        )
        webview.start()
    except Exception:
        log.exception("Native window unavailable; opening the browser instead")
        webbrowser.open(url)


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
    open_window(url)


if __name__ == "__main__":
    main()
