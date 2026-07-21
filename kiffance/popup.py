"""The one-click 'Did you kiff?' rating popup (PRD F7-F10b).

Always-on-top, bottom-right, auto-dismisses after 5 minutes, and hide() is
called the instant a new game starts — it must never be on screen during
gameplay. All methods must run on the Tk main thread.

Emoji are rendered in full color via Pillow's Segoe UI Emoji (COLR) font —
tkinter's own text rendering shows them as flat monochrome outlines.
"""

import logging
import tkinter as tk
from collections.abc import Callable
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont, ImageTk

from .config import APP_NAME, ASSETS_DIR, POPUP_TIMEOUT_SECONDS

log = logging.getLogger(__name__)

# Custom grade art, if the user supplied any (see assets/README.md).
GRADES_DIR = ASSETS_DIR / "grades"
IMAGE_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg")

# score, emoji, grade name (two lines for the popup cards)
RATINGS = [
    (1, "\U0001f6bd", "Absolute\nSkibidi"),  # toilet
    (2, "\U0001f928", "Who Let\nThem Cook?"),  # face-with-raised-eyebrow
    (3, "\U0001f9cd‍♂️", "Meh"),  # man standing
    (4, "\U0001f468‍\U0001f373", "Let Him\nCook!"),  # man cook
    (5, "\U0001f451", "Maximum\nRizz"),  # crown
]

_BG = "#1e2328"
_CARD = "#232a31"
_HOVER = "#3c434d"
_FG = "#f0e6d2"
_GOLD = "#c8aa6e"
_MUTED = "#a09b8c"
# Faces get a fixed cell, and any aspect ratio is fitted and centred inside it.
# Meme crops are rarely square (wide reaction shots, tall Chad), so a square box
# would make the row ragged and shrink the wide ones to nothing.
FACE_W, FACE_H = 104, 88
_EMOJI_PX = 60  # emoji fallback renders square inside the same cell

_EMOJI_FONT_CANDIDATES = ("seguiemj.ttf", "C:/Windows/Fonts/seguiemj.ttf")


@lru_cache(maxsize=16)
def _render_emoji(char: str, px: int) -> Image.Image | None:
    """Render one emoji to a color RGBA image, or None if no color font is found."""
    for path in _EMOJI_FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, px)
            img = Image.new("RGBA", (px + 12, px + 12), (0, 0, 0, 0))
            ImageDraw.Draw(img).text((6, 2), char, font=font, embedded_color=True)
            return img
        except Exception:  # noqa: BLE001, S112 - try next font path; text fallback covers total failure
            continue
    log.info("Color emoji font unavailable; popup will use text emoji")
    return None


def _centred(img: Image.Image, width: int, height: int) -> Image.Image:
    """Fit img inside width x height, preserving aspect, centred on transparency."""
    fitted = img.copy()
    fitted.thumbnail((width, height), Image.LANCZOS)
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.alpha_composite(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return canvas


@lru_cache(maxsize=16)
def _grade_image(score: int, emoji: str, width: int, height: int) -> Image.Image | None:
    """Custom art for this grade if present, otherwise the colour emoji.

    Lets anyone drop `assets/grades/<score>.png` in to reskin the popup with
    no code change; an empty folder keeps the built-in emoji look. Every result
    is the same cell size, so the row of faces stays aligned whatever shape the
    source art is.
    """
    for suffix in IMAGE_SUFFIXES:
        path = GRADES_DIR / f"{score}{suffix}"
        if not path.exists():
            continue
        try:
            with Image.open(path) as raw:
                return _centred(raw.convert("RGBA"), width, height)
        except Exception:
            log.exception("Could not load grade art %s; falling back to emoji", path)
    emoji_img = _render_emoji(emoji, _EMOJI_PX)
    return _centred(emoji_img, width, height) if emoji_img else None


class RatingPopup:
    def __init__(self, root: tk.Tk, on_rate: Callable[[int, int], None]):
        self._root = root
        self._on_rate = on_rate  # (game_id, score) -> None
        self._window: tk.Toplevel | None = None
        self._game_id: int | None = None
        self._timeout_job = None
        self._images: list[ImageTk.PhotoImage] = []  # keep refs alive

    def show(self, game_id: int, summary: str) -> None:
        self.hide()  # an unanswered previous popup becomes pending (F10)
        self._game_id = game_id

        win = tk.Toplevel(self._root)
        self._window = win
        win.title(APP_NAME)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.configure(bg=_BG, highlightbackground=_GOLD, highlightthickness=1)
        win.overrideredirect(True)  # borderless, chromeless card
        win.protocol("WM_DELETE_WINDOW", self.hide)  # close = pending, not lost

        tk.Label(win, text="Did you kiff?", font=("Segoe UI", 17, "bold"), bg=_BG, fg=_GOLD).pack(
            padx=26, pady=(16, 2)
        )
        tk.Label(win, text=summary, font=("Segoe UI", 10), bg=_BG, fg=_MUTED, wraplength=360).pack(
            padx=26, pady=(0, 12)
        )

        row = tk.Frame(win, bg=_BG)
        row.pack(padx=16, pady=(0, 16))
        for score, emoji, label in RATINGS:
            self._add_face(row, score, emoji, label)

        win.update_idletasks()
        x = win.winfo_screenwidth() - win.winfo_width() - 24
        y = win.winfo_screenheight() - win.winfo_height() - 72
        win.geometry(f"+{x}+{y}")

        self._timeout_job = self._root.after(POPUP_TIMEOUT_SECONDS * 1000, self.hide)

    def _add_face(self, parent: tk.Frame, score: int, emoji: str, label: str) -> None:
        card = tk.Frame(parent, bg=_CARD, cursor="hand2")
        card.pack(side=tk.LEFT, padx=5)

        img = _grade_image(score, emoji, FACE_W, FACE_H)
        if img is not None:
            photo = ImageTk.PhotoImage(img)
            self._images.append(photo)
            face = tk.Label(card, image=photo, bg=_CARD)
        else:  # fallback: monochrome text emoji still works
            face = tk.Label(card, text=emoji, font=("Segoe UI Emoji", 26), bg=_CARD)
        face.pack(padx=8, pady=(8, 0))
        name = tk.Label(
            card, text=label, font=("Segoe UI", 8), bg=_CARD, fg=_MUTED, justify="center"
        )
        name.pack(padx=6, pady=(0, 7))

        widgets = (card, face, name)
        for w in widgets:
            w.bind("<Button-1>", lambda _e, s=score: self._rate(s))
            w.bind("<Enter>", lambda _e: [x.configure(bg=_HOVER) for x in widgets])
            w.bind("<Leave>", lambda _e: [x.configure(bg=_CARD) for x in widgets])

    def hide(self) -> None:
        if self._timeout_job is not None:
            self._root.after_cancel(self._timeout_job)
            self._timeout_job = None
        if self._window is not None:
            self._window.destroy()
            self._window = None
        self._images.clear()
        self._game_id = None

    def _rate(self, score: int) -> None:
        game_id = self._game_id
        self.hide()
        if game_id is not None:
            self._on_rate(game_id, score)
