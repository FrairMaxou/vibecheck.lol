"""PyInstaller entry point.

A frozen build is a single executable, so `python -m kiffance.window` isn't
available to open the dashboard window — the exe has to relaunch *itself* with
a flag instead. This script is that dispatcher; `kiffance/__main__.py` still
handles the plain `python -m kiffance` path for development.
"""

import multiprocessing
import sys

WINDOW_FLAG = "--window"


def main() -> None:
    if WINDOW_FLAG in sys.argv:
        from kiffance.config import DASHBOARD_HOST, DASHBOARD_PORT
        from kiffance.window import open_window

        args = [a for a in sys.argv[1:] if a != WINDOW_FLAG]
        url = args[0] if args else f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
        open_window(url)
        return

    from kiffance.app import main as app_main

    app_main()


if __name__ == "__main__":
    multiprocessing.freeze_support()  # frozen apps must call this before spawning
    main()
