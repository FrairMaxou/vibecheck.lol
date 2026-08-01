"""System tray icon (PRD F22). Runs in its own thread via pystray."""

import logging
import os
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw

from .config import APP_NAME, ASSETS_DIR, DATA_DIR

log = logging.getLogger(__name__)


LOGO_PATH = ASSETS_DIR / "logo.png"


def _icon_image() -> Image.Image:
    """The user's logo if they supplied one, else the built-in gold smiley coin."""
    if LOGO_PATH.exists():
        try:
            img = Image.open(LOGO_PATH).convert("RGBA")
            img.thumbnail((64, 64), Image.LANCZOS)
            return img
        except Exception:
            log.exception("Could not load %s; using the built-in icon", LOGO_PATH)
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill="#c8aa6e")  # gold coin
    draw.ellipse((18, 22, 26, 30), fill="#1e2328")  # eyes
    draw.ellipse((38, 22, 46, 30), fill="#1e2328")
    draw.arc((16, 26, 48, 50), start=20, end=160, fill="#1e2328", width=4)  # smile
    return img


def build_tray(
    on_quit: Callable[[], None],
    on_open_dashboard: Callable[[], None],
    on_update: Callable[[], None] | None = None,
    pending_version: Callable[[], str | None] | None = None,
) -> pystray.Icon:
    """The tray icon. `pending_version` returns the newer version when one is
    known, which makes the update entry appear; the app calls `icon.update_menu()`
    after a background check so a release found mid-session shows up without a
    restart."""
    pending_version = pending_version or (lambda: None)

    # The tray stays minimal — behaviour toggles (auto-start, pause) live in the
    # dashboard's Settings tab, which is the proper home for them.
    menu = pystray.Menu(
        # Text and visibility are callables: pystray re-evaluates them each time
        # the menu opens, so this entry appears by itself once a check finds a
        # release, and names the version it found.
        pystray.MenuItem(
            lambda item: f"Update to v{pending_version()}",
            lambda: on_update and on_update(),
            visible=lambda item: bool(pending_version()),
        ),
        # default=True: double-clicking the tray icon opens the dashboard.
        pystray.MenuItem("Open dashboard", lambda: on_open_dashboard(), default=True),
        # startfile opens Explorer on our own data dir — fixed local path, not user input.
        pystray.MenuItem("Open data folder", lambda: os.startfile(DATA_DIR)),  # noqa: S606
        pystray.MenuItem("Quit", lambda: on_quit()),
    )
    return pystray.Icon(APP_NAME, _icon_image(), APP_NAME, menu)


def notify(icon: pystray.Icon, title: str, message: str) -> None:
    """Best-effort balloon. Not every backend supports notifications, and a
    failed toast is never worth taking the app down for."""
    try:
        icon.notify(message, title)
    except Exception:
        log.debug("Tray notification not shown", exc_info=True)
