"""Serve the dashboard on a throwaway database full of fake games.

For developing/previewing the dashboard without real data. Never touches the
real database.

Run: .venv\\Scripts\\python tools\\dev_dashboard.py
"""

import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vibecheck.dashboard import create_app
from vibecheck.store import GameStore

random.seed(42)

CHAMPS = ["Jhin", "Yasuo", "Lux", "Darius", "Amumu", "Jinx", "Thresh"]
# (champion, base fun, winrate) — Yasuo: wins a lot, fun rarely. Amumu: the opposite.
PROFILES = {
    "Jhin": (4.2, 0.55),
    "Yasuo": (1.9, 0.60),
    "Lux": (3.5, 0.50),
    "Darius": (3.8, 0.45),
    "Amumu": (4.5, 0.35),
    "Jinx": (3.2, 0.52),
    "Thresh": (2.8, 0.48),
}
FRIENDS = [("alex-puuid", "Alex"), ("sam-puuid", "Sam"), ("lea-puuid", "Léa")]
QUEUES = [(450, "ARAM"), (420, "Ranked Solo/Duo"), (400, "Normal Draft"), (1700, "Arena")]


def main():
    tmp = Path(tempfile.mkdtemp(prefix="vibecheck-dev-"))
    store = GameStore(tmp / "dev.sqlite3")
    when = datetime.now() - timedelta(days=30)
    game_id = 100000
    while when < datetime.now():
        session_games = random.randint(1, 5)
        for i in range(session_games):
            champ = random.choice(CHAMPS)
            base_fun, wr = PROFILES[champ]
            queue_id, queue = random.choice(QUEUES)
            with_friends = random.random() < 0.45
            premades = random.sample(FRIENDS, random.randint(1, 2)) if with_friends else []
            fun = base_fun + (0.8 if premades else 0) - 0.35 * i + random.uniform(-1, 1)
            duration = random.randint(15 * 60, 42 * 60)
            game_id += 1
            gid = store.insert_game(
                {
                    "riot_match_id": str(game_id),
                    "played_at": when.isoformat(timespec="seconds"),
                    "queue_id": queue_id,
                    "queue_type": queue,
                    "champion": champ,
                    "role": random.choice(["TOP", "JUNGLE", "MID", "BOTTOM", "UTILITY"]),
                    "win": int(random.random() < wr),
                    "kills": random.randint(0, 15),
                    "deaths": random.randint(0, 12),
                    "assists": random.randint(0, 20),
                    "cs": random.randint(20, 250),
                    "duration_seconds": duration,
                    "raw_payload": None,
                },
                [{"summoner_name": n, "riot_puuid": p, "was_premade": True} for p, n in premades],
            )
            if gid and random.random() < 0.92:  # a few stay pending
                store.set_rating(gid, max(1, min(5, round(fun))))
            when += timedelta(seconds=duration + random.randint(120, 900))
        when += timedelta(hours=random.randint(5, 40))

    print(f"Seeded {store.game_count()} fake games in {tmp}")
    uvicorn.run(create_app(store), host="127.0.0.1", port=8578, log_level="warning")


if __name__ == "__main__":
    main()
