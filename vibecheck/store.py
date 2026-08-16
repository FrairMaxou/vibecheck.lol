"""The game store: the ONLY module that touches SQLite (PRD §11 constraint #1).

Feature code never issues SQL — everything goes through this interface so a
future "also sync to server" backend can plug in behind it.
"""

import json
import logging
import shutil
import sqlite3
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from .config import DB_PATH, DEFAULT_TAGS, SESSION_GAP_SECONDS

log = logging.getLogger(__name__)

# Baseline table creation only — applied unconditionally on every launch, with
# no backup and no version gate. New structural changes (new columns, new
# tables, anything that mutates an existing shape) belong in `_MIGRATIONS`
# below, not here: that's what gets a pre-change backup and a schema_version
# bump. `CREATE TABLE IF NOT EXISTS` is safe to run forever unversioned;
# anything less idempotent than that does not belong in this constant.
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
    raw_payload TEXT,
    enemy_champions TEXT,
    augments TEXT,
    items TEXT,
    damage_to_champs INTEGER,
    gold INTEGER
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
-- Achievement progress (PRD §16). Definitions live in code; only progress is
-- data, so this table never learns what an achievement *is*.
--
-- champion_id is 0, not NULL, for a goal that isn't per-champion: SQLite treats
-- NULLs as distinct in a UNIQUE index, so a nullable column in the primary key
-- would let the same counter be inserted twice and silently double.
CREATE TABLE IF NOT EXISTS achievement_progress (
    key TEXT NOT NULL,
    champion_id INTEGER NOT NULL DEFAULT 0,
    state TEXT,
    value REAL,
    source TEXT,
    updated_at TEXT,
    PRIMARY KEY (key, champion_id)
);
"""


def _step_v1_added_columns(conn: sqlite3.Connection) -> None:
    """v1: the pre-versioning ALTER-by-existence-check pass, unchanged in
    behavior from before schema_version existed. Idempotent by column
    existence, so a database mid-way through the old scheme (some columns
    already added by an earlier build) still ends up complete no matter what
    version it starts this migration at.
    """
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(games)")}
    for name, decl in (
        ("enemy_champions", "TEXT"),
        ("augments", "TEXT"),
        ("items", "TEXT"),
        ("damage_to_champs", "INTEGER"),
        ("gold", "INTEGER"),
    ):
        if name not in existing:
            # Names are fixed literals above, never user input.
            conn.execute(f"ALTER TABLE games ADD COLUMN {name} {decl}")  # noqa: S608
            log.info("Migrated games table: added column %s", name)


def _step_v2_added_pending_capture_columns(conn: sqlite3.Connection) -> None:
    """v2: pending two-phase capture (issue #96) — a game can be inserted as
    a stub (rating only, no stats yet) while Arena's match-history sync
    catches up, then completed in place once the real data arrives.
    """
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(games)")}
    if "resolved" not in existing:
        conn.execute("ALTER TABLE games ADD COLUMN resolved INTEGER NOT NULL DEFAULT 1")
        log.info("Migrated games table: added column resolved")
    if "pending_premades" not in existing:
        conn.execute("ALTER TABLE games ADD COLUMN pending_premades TEXT")
        log.info("Migrated games table: added column pending_premades")


class GameStore:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db_path = db_path
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row

        # Check if migrations are pending before applying schema — if so, back up
        # the database in its current state before any structural changes. This
        # is the single computation of "pending": _migrate() takes the list
        # below rather than recomputing it, so the backup's target version and
        # the migration loop's target version can never diverge, and _migrate()
        # can't run without first going through this backup gate.
        current = self._read_schema_version()
        pending = [step for step in self._MIGRATIONS if step[0] > current]
        self._schema_version = current
        self._migration_failed = False
        backup_succeeded = True
        if pending:
            target_version = pending[-1][0]
            try:
                self._backup_before_migration(target_version)
            except Exception:
                # Broad on purpose, same as the step loop below: a migration
                # step (and the backup step that guards it) must never crash
                # the app. Narrowing this to OSError would let anything else
                # _backup_before_migration raises propagate out of the
                # constructor and take app startup down with it — the exact
                # failure mode this framework exists to prevent.
                log.exception(
                    "Could not back up database before migrating to v%d; skipping this launch",
                    target_version,
                )
                self._migration_failed = True
                backup_succeeded = False

        with self._lock, self._db:
            self._db.executescript(_SCHEMA)
        if pending and backup_succeeded:
            self._migrate(pending)
        self._seed_default_tags()

    # ---------------- schema migrations (issue #49) ----------------
    #
    # Each entry is (target_version, description, step). A step receives the
    # raw sqlite3.Connection and runs DDL/DML against it directly — it already
    # runs inside a lock+transaction held by _migrate(), so it must never call
    # a public helper like get_meta/set_meta (self._lock is not reentrant).
    _MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...] = (
        (
            1,
            "add enemy_champions/augments/items/damage_to_champs/gold columns",
            _step_v1_added_columns,
        ),
        (
            2,
            "add resolved/pending_premades columns for two-phase Arena capture",
            _step_v2_added_pending_capture_columns,
        ),
    )
    # Fields stored as JSON arrays.
    _JSON_COLUMNS = ("enemy_champions", "augments", "items")

    def _read_schema_version(self) -> int:
        try:
            value = self.get_meta("schema_version")
            return int(value) if value else 0
        except sqlite3.OperationalError:
            # meta table doesn't exist yet (fresh database before _SCHEMA is applied)
            return 0

    def _backup_before_migration(self, target_version: int) -> None:
        """Copy the database into <data dir>/backups/ before the first DDL of a
        new schema version — the safety net for ~100 users' live history if a
        step turns out to be wrong. Mirrors the naming tools/reset_data.py
        already uses for its own timestamped backups.
        """
        backups_dir = self._db_path.parent / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        dest = backups_dir / f"{timestamp}-schema-v{target_version}.sqlite3"
        shutil.copy2(self._db_path, dest)
        log.info("Backed up database to %s before migrating to schema v%d", dest, target_version)

    def _migrate(
        self, pending: list[tuple[int, str, Callable[[sqlite3.Connection], None]]]
    ) -> None:
        """Run each pending migration step in its own transaction.

        Only called from __init__, after the backup gate there has already
        run for this exact `pending` list — never call this directly, and
        never recompute "pending" here, or the backup's target version and
        this loop's target version could diverge.
        """
        for version, description, step_fn in pending:
            try:
                with self._lock, self._db:
                    # isolation_level="" (the default) only opens an implicit
                    # transaction before DML (INSERT/UPDATE/DELETE) — never
                    # before DDL. A bare `with self._db:` here would let a
                    # step's ALTER TABLE/CREATE TABLE autocommit immediately,
                    # so it would survive even though the `with` block rolls
                    # back on a later exception in the same step. BEGIN
                    # explicitly so DDL joins the same transaction as the rest
                    # of the step and actually rolls back with it.
                    self._db.execute("BEGIN")
                    step_fn(self._db)
                    self._db.execute(
                        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (str(version),),
                    )
            except Exception:
                # A migration step must never take the app down: a user seeing
                # an empty dashboard reads as "it deleted everything", so this
                # logs loudly and keeps running on the last version that
                # worked rather than propagating. self._schema_version already
                # reflects that version — updated per-step below, not just
                # once at the end — so it stays truthful even when an earlier
                # step in this same pass committed before a later one failed.
                log.exception(
                    "Schema migration to v%d (%s) failed; staying on v%d",
                    version,
                    description,
                    self._schema_version,
                )
                self._migration_failed = True
                return
            # Updated after each successful step, not once after the whole
            # loop — a later step can still fail, and self._schema_version
            # must reflect what actually got committed, not what was intended.
            self._schema_version = version

    def _seed_default_tags(self) -> None:
        with self._lock, self._db:
            if self._db.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 0:
                self._db.executemany(
                    "INSERT OR IGNORE INTO tags (label) VALUES (?)",
                    [(label,) for label in DEFAULT_TAGS],
                )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def schema_version(self) -> int:
        """Current schema version, after whatever migration ran at open."""
        return self._schema_version

    def schema_migration_failed(self) -> bool:
        """Whether the most recent startup's migration attempt failed, leaving
        the database on an older version than the code expects.
        """
        return self._migration_failed

    def _bump_rev(self) -> None:
        """Mark the dataset as changed. Call only from inside a `with self._lock,
        self._db:` block already held by the caller (see every write method below) —
        the dashboard polls data_revision() to know when a re-fetch is worth doing.
        """
        self._db.execute(
            "INSERT INTO meta (key, value) VALUES ('data_rev', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = CAST(CAST(value AS INTEGER) + 1 AS TEXT)"
        )

    def data_revision(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'data_rev'").fetchone()
        return int(row["value"]) if row else 0

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
                    session_id, game_index_in_session, is_remake, raw_payload,
                    enemy_champions, augments, items, damage_to_champs, gold)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                    json.dumps(game.get("enemy_champions") or []),
                    json.dumps(game.get("augments") or []),
                    json.dumps(game.get("items") or []),
                    game.get("damage_to_champs"),
                    game.get("gold"),
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
            self._bump_rev()
            return game_id

    def insert_pending_game(
        self, riot_match_id: str, played_at: str, premade_puuids: set
    ) -> int | None:
        """Insert a minimal stub for a game whose stats aren't available yet
        (issue #96 — Arena's local match-history sync can take minutes).

        Rateable immediately via the returned id, same as insert_game's.
        `premade_puuids` is frozen here rather than left in the caller's
        single shared slot, because that slot gets overwritten the moment
        the player queues into their next game — which routinely happens
        before this one resolves.
        """
        with self._lock, self._db:
            session_id, game_index = self._session_for(played_at)
            cur = self._db.execute(
                """INSERT OR IGNORE INTO games
                   (riot_match_id, played_at, session_id, game_index_in_session,
                    resolved, pending_premades)
                   VALUES (?,?,?,?,0,?)""",
                (
                    riot_match_id,
                    played_at,
                    session_id,
                    game_index,
                    json.dumps(sorted(premade_puuids)),
                ),
            )
            if cur.rowcount == 0:
                return None
            self._bump_rev()
            return cur.lastrowid

    def complete_game(self, game_id: int, game: dict, teammates: list) -> bool:
        """Fill in real stats for a pending stub (issue #96), in place.

        Only played_at and the stat/detail columns change — session_id and
        game_index_in_session stay as assigned at pending-insert time (see
        "Known limitation" in the #96 plan). Returns False if the row is
        missing or already resolved, so a duplicate resolution attempt is a
        safe no-op rather than a second insert or a crash.
        """
        with self._lock, self._db:
            cur = self._db.execute(
                """UPDATE games SET
                       played_at=?, queue_id=?, queue_type=?, champion=?, role=?,
                       win=?, kills=?, deaths=?, assists=?, cs=?, duration_seconds=?,
                       is_remake=?, raw_payload=?, enemy_champions=?, augments=?,
                       items=?, damage_to_champs=?, gold=?, resolved=1, pending_premades=NULL
                   WHERE id=? AND resolved=0""",
                (
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
                    game.get("is_remake", 0),
                    json.dumps(game.get("raw_payload")) if game.get("raw_payload") else None,
                    json.dumps(game.get("enemy_champions") or []),
                    json.dumps(game.get("augments") or []),
                    json.dumps(game.get("items") or []),
                    game.get("damage_to_champs"),
                    game.get("gold"),
                    game_id,
                ),
            )
            if cur.rowcount == 0:
                return False
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
            self._bump_rev()
            return True

    def unresolved_games(self) -> list:
        """Pending stubs still waiting on real stats (issue #96)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, riot_match_id, pending_premades, played_at "
                "FROM games WHERE resolved = 0"
            ).fetchall()
        return [dict(r) for r in rows]

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
            self._bump_rev()

    def pending_games(self) -> list:
        """Games not yet rated or skipped (PRD F11).

        Keyed on fun_score, not the ratings row's existence, so a game that
        only has a note attached still counts as pending.
        """
        with self._lock:
            rows = self._db.execute(
                """SELECT g.* FROM games g
                   LEFT JOIN ratings r ON r.game_id = g.id
                   WHERE r.fun_score IS NULL AND COALESCE(r.skipped, 0) = 0
                     AND g.is_remake = 0
                   ORDER BY g.played_at DESC"""
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------------- tags & notes (F9) ----------------

    def list_tags(self) -> list:
        with self._lock:
            rows = self._db.execute("SELECT label FROM tags ORDER BY label").fetchall()
        return [r["label"] for r in rows]

    def _ensure_tag(self, label: str) -> int:
        """Return a tag id, creating the tag if the label is new (user-editable list)."""
        self._db.execute("INSERT OR IGNORE INTO tags (label) VALUES (?)", (label,))
        return self._db.execute("SELECT id FROM tags WHERE label = ?", (label,)).fetchone()["id"]

    def set_game_tags(self, game_id: int, labels: list) -> None:
        """Replace a game's tags with the given labels (unknown labels are created)."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM game_tags WHERE game_id = ?", (game_id,))
            for label in labels:
                clean = label.strip()
                if clean:
                    tag_id = self._ensure_tag(clean)
                    self._db.execute(
                        "INSERT INTO game_tags (game_id, tag_id) VALUES (?,?)", (game_id, tag_id)
                    )
            self._bump_rev()

    def set_note(self, game_id: int, note: str) -> None:
        """Attach a free-text note without disturbing the fun score."""
        with self._lock, self._db:
            self._db.execute(
                """INSERT INTO ratings (game_id, note) VALUES (?,?)
                   ON CONFLICT(game_id) DO UPDATE SET note=excluded.note""",
                (game_id, note),
            )
            self._bump_rev()

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

    # ---------------- achievements (PRD §16) ----------------

    def set_achievement_champions(self, key: str, champion_ids, source: str = "client") -> bool:
        """Replace the completed-champion set for an achievement.

        Returns whether anything actually changed, so the caller can avoid
        bumping the data revision — this is re-read on every League client
        connect, and an unconditional bump would make an open dashboard reload
        itself every time the client restarts.

        Callers must never pass an empty list to mean "couldn't read it": that
        would erase a lifetime figure the app cannot rebuild from its own
        games. See `lcu.completed_champion_ids`, which returns None for that.
        """
        wanted = sorted({int(c) for c in champion_ids if int(c) > 0})
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._db:
            rows = self._db.execute(
                "SELECT champion_id FROM achievement_progress WHERE key = ? AND champion_id > 0",
                (key,),
            ).fetchall()
            current = sorted(r["champion_id"] for r in rows)
            changed = current != wanted
            if changed:
                self._db.execute(
                    "DELETE FROM achievement_progress WHERE key = ? AND champion_id > 0", (key,)
                )
                self._db.executemany(
                    """INSERT INTO achievement_progress
                       (key, champion_id, state, value, source, updated_at)
                       VALUES (?,?,'completed',1,?,?)""",
                    [(key, champ_id, source, now) for champ_id in wanted],
                )
            # The summary row (champion_id 0) is rewritten either way: it
            # carries when we last *checked*, which is the difference between
            # "no progress" and "never synced" in the UI.
            self._db.execute(
                """INSERT INTO achievement_progress
                   (key, champion_id, state, value, source, updated_at)
                   VALUES (?,0,'synced',?,?,?)
                   ON CONFLICT(key, champion_id) DO UPDATE SET
                       state=excluded.state, value=excluded.value,
                       source=excluded.source, updated_at=excluded.updated_at""",
                (key, float(len(wanted)), source, now),
            )
            if changed:
                self._bump_rev()
        return changed

    def achievement_progress(self, key: str) -> dict:
        """Stored progress for one achievement.

        `synced_at` is None when the app has never managed to read it — which
        the UI must distinguish from a real zero, or a brand-new install shows
        a confident 0/173 that is simply a lie.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT champion_id, source, updated_at FROM achievement_progress WHERE key = ?",
                (key,),
            ).fetchall()
        summary = next((r for r in rows if r["champion_id"] == 0), None)
        return {
            "champion_ids": sorted(r["champion_id"] for r in rows if r["champion_id"] > 0),
            "source": summary["source"] if summary else None,
            "synced_at": summary["updated_at"] if summary else None,
        }

    def delete_game(self, game_id: int) -> None:
        """Remove a game and all its related rows (rating, teammates, tags)."""
        with self._lock, self._db:
            self._db.execute("DELETE FROM game_tags WHERE game_id = ?", (game_id,))
            self._db.execute("DELETE FROM game_teammates WHERE game_id = ?", (game_id,))
            self._db.execute("DELETE FROM ratings WHERE game_id = ?", (game_id,))
            self._db.execute("DELETE FROM games WHERE id = ?", (game_id,))
            self._bump_rev()

    def set_premades(self, game_id: int, puuids: list) -> None:
        """Set which of a game's teammates were premades (lobby-derived).

        Used to repair games captured while the lobby snapshot was unavailable —
        e.g. the app restarting mid-game, which used to lose it entirely.
        """
        with self._lock, self._db:
            self._db.execute(
                "UPDATE game_teammates SET was_premade = 0 WHERE game_id = ?", (game_id,)
            )
            if puuids:
                marks = ",".join("?" * len(puuids))
                self._db.execute(
                    "UPDATE game_teammates SET was_premade = 1 "  # noqa: S608 - placeholders only
                    f"WHERE game_id = ? AND riot_puuid IN ({marks})",
                    (game_id, *puuids),
                )
            self._bump_rev()

    def update_queue_type(self, game_id: int, queue_type: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE games SET queue_type = ? WHERE id = ?", (queue_type, game_id))
            self._bump_rev()

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
                   WHERE g.resolved = 1
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
                          g.is_remake, g.enemy_champions, g.augments, g.items,
                   g.damage_to_champs, g.gold,
                   r.fun_score, r.skipped, r.rated_at, r.note
                   FROM games g LEFT JOIN ratings r ON r.game_id = g.id
                   WHERE g.resolved = 1
                   ORDER BY g.played_at"""
            ).fetchall()
            mates = self._db.execute(
                "SELECT game_id, summoner_name, riot_puuid, was_premade FROM game_teammates"
            ).fetchall()
            tags = self._db.execute(
                """SELECT gt.game_id, t.label FROM game_tags gt
                   JOIN tags t ON t.id = gt.tag_id"""
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
        tags_by_game: dict = {}
        for t in tags:
            tags_by_game.setdefault(t["game_id"], []).append(t["label"])
        out = []
        for row in games:
            game = dict(row)
            game["teammates"] = teammates_by_game.get(game["id"], [])
            game["tags"] = tags_by_game.get(game["id"], [])
            for col in self._JSON_COLUMNS:
                try:
                    game[col] = json.loads(game[col]) if game.get(col) else []
                except (TypeError, ValueError):
                    game[col] = []
            out.append(game)
        return out

    def set_analysis_fields(self, game_id: int, fields: dict) -> None:
        """Populate the §13 analysis columns (used by the backfill tool)."""
        with self._lock, self._db:
            self._db.execute(
                """UPDATE games SET enemy_champions=?, augments=?, items=?,
                                    damage_to_champs=?, gold=?
                   WHERE id=?""",
                (
                    json.dumps(fields.get("enemy_champions") or []),
                    json.dumps(fields.get("augments") or []),
                    json.dumps(fields.get("items") or []),
                    fields.get("damage_to_champs"),
                    fields.get("gold"),
                    game_id,
                ),
            )
            self._bump_rev()

    def games_with_raw(self) -> list:
        """Every game that kept its payload — the input for backfills/relabels.

        Includes the stored queue fields so a relabel can skip rows that already
        have the right label instead of rewriting (and bumping the revision for)
        every game.
        """
        with self._lock:
            rows = self._db.execute(
                "SELECT id, queue_id, queue_type, raw_payload FROM games "
                "WHERE raw_payload IS NOT NULL"
            ).fetchall()
        return [dict(r) for r in rows]

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
