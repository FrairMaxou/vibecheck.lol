"""System tray icon (PRD F22). Runs in its own thread via pystray."""

import os
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw

from .config import APP_NAME, DATA_DIR


def _icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((4, 4, 60, 60), fill="#c8aa6e")  # gold coin
    draw.ellipse((18, 22, 26, 30), fill="#1e2328")  # eyes
    draw.ellipse((38, 22, 46, 30), fill="#1e2328")
    draw.arc((16, 26, 48, 50), start=20, end=160, fill="#1e2328", width=4)  # smile
    return img


def build_tray(
    is_paused: Callable[[], bool], toggle_paused: Callable[[], None], on_quit: Callable[[], None]
) -> pystray.Icon:
    menu = pystray.Menu(
        pystray.MenuItem(
            "Pause prompts", lambda: toggle_paused(), checked=lambda _item: is_paused()
        ),
        # startfile opens Explorer on our own data dir — fixed local path, not user input.
        pystray.MenuItem("Open data folder", lambda: os.startfile(DATA_DIR)),  # noqa: S606
        pystray.MenuItem("Quit", lambda: on_quit()),
    )
    return pystray.Icon(APP_NAME, _icon_image(), APP_NAME, menu)
