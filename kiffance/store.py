"""The game store: the ONLY module that touches SQLite (PRD §11 constraint #1).

Feature code never issues SQL — everything goes through this interface so a
future "also sync to server" backend can plug in behind it.
"""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from .config import DB_PATH, SESSION_GAP_SECONDS

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY,
    riot_match_id TEXT UNIQUE,
    played_at TEXT NOT NULL,
    queue_id INTEGER,
    queue_type TEXT,
    champion TEXT,
    role TEXT,
    win INTEGER,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    cs INTEGER,
    duration_seconds INTEGER,
    session_id INTEGER,
    game_index_in_session INTEGER,
    is_remake INTEGER DEFAULT 0,
    raw_payload TEXT
);
CREATE TABLE IF NOT EXISTS ratings (
    game_id INTEGER PRIMARY KEY REFERENCES games(id),
    fun_score INTEGER,
    skipped INTEGER DEFAULT 0,
    rated_at TEXT,
    note TEXT
);
CREATE TABLE IF NOT EXISTS game_teammates (
    game_id INTEGER REFERENCES games(id),
    summoner_name TEXT,
    riot_puuid TEXT,
    was_premade INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY,
    label TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS game_tags (
    game_id INTEGER REFERENCES games(id),
    tag_id INTEGER REFERENCES tags(id)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class GameStore:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def insert_game(self, game: dict, teammates: list) -> int | None:
        """Insert a captured game; returns its id, or None if already stored.

        `game` keys mirror the games table; `teammates` is a list of
        {summoner_name, riot_puuid, was_premade}.
        """
        with self._lock, self._db:
            session_id, game_index = self._session_for(game["played_at"])
            cur = self._db.execute(
                """INSERT OR IGNORE INTO games
                   (riot_match_id, played_at, queue_id, queue_type, champion, role,
                    win, kills, deaths, assists, cs, duration_seconds,
                    session_id, game_index_in_session, is_remake, raw_payload)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    game.get("riot_match_id"),
                    game["played_at"],
                    game.get("queue_id"),
                    game.get("queue_type"),
                    game.get("champion"),
                    game.get("role"),
                    game.get("win"),
                    game.get("kills"),
                    game.get("deaths"),
                    game.get("assists"),
                    game.get("cs"),
                    game.get("duration_seconds"),
                    session_id,
                    game_index,
                    game.get("is_remake", 0),
                    json.dumps(game.get("raw_payload")) if game.get("raw_payload") else None,
                ),
            )
            if cur.rowcount == 0:
                return None
            game_id = cur.lastrowid
            self._db.executemany(
                """INSERT INTO game_teammates (game_id, summoner_name, riot_puuid, was_premade)
                   VALUES (?,?,?,?)""",
                [
                    (
                        game_id,
                        t.get("summoner_name"),
                        t.get("riot_puuid"),
                        int(t.get("was_premade", 0)),
                    )
                    for t in teammates
                ],
            )
            return game_id

    def set_rating(self, game_id: int, fun_score: int | None, skipped: bool = False) -> None:
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO ratings (game_id, fun_score, skipped, rated_at)
                   VALUES (?,?,?,?)
                   ON CONFLICT(game_id) DO UPDATE
                   SET fun_score=excluded.fun_score, skipped=excluded.skipped,
                       rated_at=excluded.rated_at""",
                (game_id, fun_score, int(skipped), datetime.now().isoformat(timespec="seconds")),
            )

    def pending_games(self) -> list:
        """Games with no rating yet (PRD F11)."""
        with self._lock:
            rows = self._db.execute(
                """SELECT g.* FROM games g
                   LEFT JOIN ratings r ON r.game_id = g.id
                   WHERE r.game_id IS NULL AND g.is_remake = 0
                   ORDER BY g.played_at DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )

    def has_game(self, riot_match_id: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM games WHERE riot_match_id = ?", (riot_match_id,)
            ).fetchone()
        return row is not None

    def recent_games(self, limit: int = 10) -> list:
        """Latest games with their rating (fun_score is NULL while pending)."""
        with self._lock:
            rows = self._db.execute(
                """SELECT g.id, g.played_at, g.queue_type, g.champion, g.role, g.win,
                          g.kills, g.deaths, g.assists, g.duration_seconds,
                          g.session_id, g.game_index_in_session,
                          r.fun_score, r.skipped, r.rated_at
                   FROM games g
                   LEFT JOIN ratings r ON r.game_id = g.id
                   ORDER BY g.played_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def games_with_details(self) -> list:
        """Every game with rating fields and teammates — the dashboard's dataset.

        raw_payload is excluded (large, and the dashboard never needs it).
        """
        with self._lock:
            games = self._db.execute(
                """SELECT g.id, g.riot_match_id, g.played_at, g.queue_id, g.queue_type,
                          g.champion, g.role, g.win, g.kills, g.deaths, g.assists, g.cs,
                          g.duration_seconds, g.session_id, g.game_index_in_session,
                          g.is_remake, r.fun_score, r.skipped, r.rated_at
                   FROM games g LEFT JOIN ratings r ON r.game_id = g.id
                   ORDER BY g.played_at"""
            ).fetchall()
            mates = self._db.execute(
                "SELECT game_id, summoner_name, riot_puuid, was_premade FROM game_teammates"
            ).fetchall()
        teammates_by_game: dict = {}
        for m in mates:
            teammates_by_game.setdefault(m["game_id"], []).append(
                {
                    "name": m["summoner_name"],
                    "puuid": m["riot_puuid"],
                    "was_premade": bool(m["was_premade"]),
                }
            )
        out = []
        for row in games:
            game = dict(row)
            game["teammates"] = teammates_by_game.get(game["id"], [])
            out.append(game)
        return out

    def game_count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM games").fetchone()[0]

    def _session_for(self, played_at: str) -> tuple:
        """Session = games whose start is < 1h after the previous game's end."""
        row = self._db.execute(
            """SELECT session_id, game_index_in_session, played_at, duration_seconds
               FROM games ORDER BY played_at DESC LIMIT 1"""
        ).fetchone()
        if row is None or row["session_id"] is None:
            return 1, 1
        try:
            prev_end = datetime.fromisoformat(row["played_at"]).timestamp() + (
                row["duration_seconds"] or 0
            )
            gap = datetime.fromisoformat(played_at).timestamp() - prev_end
        except ValueError:
            gap = SESSION_GAP_SECONDS + 1
        if 0 <= gap < SESSION_GAP_SECONDS:
            return row["session_id"], (row["game_index_in_session"] or 0) + 1
        return row["session_id"] + 1, 1
