"""Show the rating popup with fake data — no League needed.

Tests the popup visuals and click flow in isolation. The click is printed,
not stored.

Run: .venv\\Scripts\\python tools\\preview_popup.py
"""

import sys
import tkinter as tk
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vibecheck.popup import RatingPopup


def main():
    root = tk.Tk()
    root.withdraw()

    def on_rate(game_id: int, score: int):
        print(f"clicked: {score}/5 (game_id={game_id}) — popup works!")
        root.after(200, root.destroy)

    popup = RatingPopup(root, on_rate)
    popup.show(game_id=999, summary="Jhin  ·  Victory  ·  12/3/9  ·  ARAM")
    print("Popup shown (bottom-right of your screen). Click an emoji...")
    root.mainloop()


if __name__ == "__main__":
    main()
