"""Serve the dashboard on a throwaway database full of fake games.

For developing/previewing the dashboard without real data. Never touches the
real database.

Run: .venv\\Scripts\\python tools\\dev_dashboard.py
"""

import json
import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vibecheck.config import ARAM_GOD_KEY, ASSETS_CHAMPS_KEY
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

    _seed_aram_god(store)
    print(f"Seeded {store.game_count()} fake games in {tmp}")
    uvicorn.run(create_app(store), host="127.0.0.1", port=8578, log_level="warning")


def _seed_aram_god(store):
    """Fake a partly-done ARAM God run so the panel is previewable.

    The real numbers come from the League client, which this harness has no
    business talking to — but a panel you can only see by playing 173 ARAM
    games is a panel nobody will style correctly. Includes a League Classic
    variant id (60001) in the roster to prove the denominator drops it.
    """
    roster = {
        1: "Annie",
        2: "Olaf",
        3: "Galio",
        4: "Twisted Fate",
        9: "Fiddlesticks",
        11: "Master Yi",
        12: "Alistar",
        17: "Teemo",
        22: "Ashe",
        51: "Caitlyn",
        64: "Lee Sin",
        89: "Leona",
        103: "Ahri",
        157: "Yasuo",
        222: "Jinx",
        412: "Thresh",
        32: "Amumu",
        122: "Darius",
        99: "Lux",
        202: "Jhin",
        60001: "Annie",  # League Classic variant — must not inflate the total
    }
    store.set_meta(ASSETS_CHAMPS_KEY, json.dumps(roster))
    done = [1, 3, 11, 22, 89, 103, 202, 412]
    store.set_achievement_champions(ARAM_GOD_KEY, done, source="client")
    print(f"Seeded ARAM God: {len(done)} of {len(set(roster.values()))} champions")


if __name__ == "__main__":
    main()
