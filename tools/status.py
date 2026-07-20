"""Quick health check: is capture working? What's in the database?

Run: .venv\\Scripts\\python tools\\status.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiffance.config import DB_PATH, LOG_PATH
from kiffance.store import GameStore

EMOJI = {1: "\U0001f621", 2: "\U0001f615", 3: "\U0001f610", 4: "\U0001f642", 5: "\U0001f929"}


def main():
    print(f"Database: {DB_PATH}")
    if not DB_PATH.exists():
        print("  -> no database yet: the app hasn't captured anything. Is it running?")
        return

    store = GameStore()
    total = store.game_count()
    pending = store.pending_games()
    print(f"Games captured: {total}   Pending rating: {len(pending)}\n")

    if total:
        print("Recent games:")
        for g in store.recent_games(10):
            fun = EMOJI.get(g["fun_score"], "skipped" if g["skipped"] else "PENDING")
            result = {1: "W", 0: "L"}.get(g["win"], "?")
            kda = (
                f"{g['kills']}/{g['deaths']}/{g['assists']}" if g["kills"] is not None else "?/?/?"
            )
            mins = (g["duration_seconds"] or 0) // 60
            print(
                f"  [{g['played_at']}] {g['queue_type'] or '?':<24} "
                f"{g['champion'] or '?':<14} {result}  {kda:<9} {mins:>3}min  "
                f"session {g['session_id']}.{g['game_index_in_session']}  fun: {fun}"
            )
    store.close()

    print(f"\nLog: {LOG_PATH}")
    if LOG_PATH.exists():
        lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
        print(f"  last activity: {lines[-1] if lines else '(empty)'}")
        connected = any("Connected to League client" in ln for ln in lines[-50:])
        lost = [i for i, ln in enumerate(lines) if "connection lost" in ln]
        conn = [i for i, ln in enumerate(lines) if "Connected to League client" in ln]
        if conn and (not lost or lost[-1] < conn[-1]):
            print("  status: connected to the League client")
        elif connected:
            print("  status: connection to the League client was lost; waiting to reconnect")
        else:
            print("  status: not connected — is League (and the tray app) running?")
    print(f"\nChecked at {datetime.now().isoformat(timespec='seconds')}")


if __name__ == "__main__":
    main()
