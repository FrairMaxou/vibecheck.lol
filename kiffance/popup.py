"""The one-click 'Had fun?' rating popup (PRD F7-F10b).

Always-on-top, bottom-right, auto-dismisses after 5 minutes, and hide() is
called the instant a new game starts — it must never be on screen during
gameplay. All methods must run on the Tk main thread.
"""

import tkinter as tk
from collections.abc import Callable

from .config import APP_NAME, POPUP_TIMEOUT_SECONDS

RATINGS = [
    (1, "\U0001f621"),
    (2, "\U0001f615"),
    (3, "\U0001f610"),
    (4, "\U0001f642"),
    (5, "\U0001f929"),
]

_BG = "#1e2328"
_FG = "#f0e6d2"


class RatingPopup:
    def __init__(self, root: tk.Tk, on_rate: Callable[[int, int], None]):
        self._root = root
        self._on_rate = on_rate  # (game_id, score) -> None
        self._window: tk.Toplevel | None = None
        self._game_id: int | None = None
        self._timeout_job = None

    def show(self, game_id: int, summary: str) -> None:
        self.hide()  # an unanswered previous popup becomes pending (F10)
        self._game_id = game_id

        win = tk.Toplevel(self._root)
        self._window = win
        win.title(APP_NAME)
        win.attributes("-topmost", True)
        win.resizable(False, False)
        win.configure(bg=_BG)
        win.protocol("WM_DELETE_WINDOW", self.hide)  # close = pending, not lost

        tk.Label(win, text="Had fun?", font=("Segoe UI", 16, "bold"), bg=_BG, fg=_FG).pack(
            padx=24, pady=(16, 2)
        )
        tk.Label(win, text=summary, font=("Segoe UI", 10), bg=_BG, fg="#a09b8c").pack(
            padx=24, pady=(0, 10)
        )

        row = tk.Frame(win, bg=_BG)
        row.pack(padx=18, pady=(0, 16))
        for score, emoji in RATINGS:
            btn = tk.Label(row, text=emoji, font=("Segoe UI Emoji", 26), bg=_BG, cursor="hand2")
            btn.pack(side=tk.LEFT, padx=7)
            btn.bind("<Button-1>", lambda _e, s=score: self._rate(s))
            btn.bind("<Enter>", lambda _e, b=btn: b.configure(bg="#3c3f45"))
            btn.bind("<Leave>", lambda _e, b=btn: b.configure(bg=_BG))

        win.update_idletasks()
        x = win.winfo_screenwidth() - win.winfo_width() - 24
        y = win.winfo_screenheight() - win.winfo_height() - 72
        win.geometry(f"+{x}+{y}")

        self._timeout_job = self._root.after(POPUP_TIMEOUT_SECONDS * 1000, self.hide)

    def hide(self) -> None:
        if self._timeout_job is not None:
            self._root.after_cancel(self._timeout_job)
            self._timeout_job = None
        if self._window is not None:
            self._window.destroy()
            self._window = None
        self._game_id = None

    def _rate(self, score: int) -> None:
        game_id = self._game_id
        self.hide()
        if game_id is not None:
            self._on_rate(game_id, score)
