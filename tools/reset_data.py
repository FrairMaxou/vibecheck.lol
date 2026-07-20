"""Fresh start: archive the current database and log into a timestamped backup.

Nothing is deleted — data moves to %LOCALAPPDATA%\\LeagueOfKiffance\\backups\\<timestamp>\\.
The app recreates an empty database on next launch. Quit the app first (tray -> Quit):
Windows locks the database file while the app is running.

Run: .venv\\Scripts\\python tools\\reset_data.py
"""

import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiffance.config import DATA_DIR, DB_PATH, LOG_PATH


def main():
    to_archive = [p for p in (DB_PATH, LOG_PATH) if p.exists()]
    if not to_archive:
        print("Nothing to reset — no database or log found. You're already fresh.")
        return

    backup_dir = DATA_DIR / "backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)

    for path in to_archive:
        try:
            shutil.move(str(path), str(backup_dir / path.name))
            print(f"archived: {path.name} -> {backup_dir}")
        except PermissionError:
            print(f"LOCKED: {path.name} is in use.")
            print("Quit the app first (tray icon -> Quit), then run this again.")
            return

    print("\nDone. Start the app again (start-kiffance.bat) for a fresh database.")
    print(f"Old data is safe in: {backup_dir}")


if __name__ == "__main__":
    main()
