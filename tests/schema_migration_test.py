"""Verify schema versioning: ordered steps, per-step transactions, and
failure isolation (issue #49). Backup coverage lives in the tests added
alongside it once the backup step exists.

Run: .venv\\Scripts\\python tests\\schema_migration_test.py
"""

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from vibecheck.store import GameStore  # noqa: E402

LATEST_VERSION = GameStore._MIGRATIONS[-1][0]


def test_fresh_database_lands_on_latest_version(root):
    store = GameStore(root / "fresh.sqlite3")
    assert store._schema_version == LATEST_VERSION
    assert store._migration_failed is False
    store.close()


def test_old_partial_columns_database_still_completes(root):
    """A database shaped like the pre-versioning scheme — no schema_version
    key at all, and only some of the old _ADDED_COLUMNS present — must still
    end up complete, because that's every real database in production today.
    """
    db_path = root / "partial.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE games (id INTEGER PRIMARY KEY, riot_match_id TEXT UNIQUE,
                             played_at TEXT NOT NULL, enemy_champions TEXT);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO games (riot_match_id, played_at, enemy_champions)
            VALUES ('m1', '2099-01-01T00:00:00', '["Ahri"]');
        """
    )
    conn.commit()
    conn.close()

    store = GameStore(db_path)
    cols = {r["name"] for r in store._db.execute("PRAGMA table_info(games)")}
    assert {"augments", "items", "damage_to_champs", "gold"} <= cols, cols
    row = store._db.execute(
        "SELECT enemy_champions FROM games WHERE riot_match_id = 'm1'"
    ).fetchone()
    assert row["enemy_champions"] == '["Ahri"]', "existing data must survive untouched"
    assert store._schema_version == LATEST_VERSION
    store.close()


def test_second_launch_is_a_noop(root):
    db_path = root / "twice.sqlite3"
    store = GameStore(db_path)
    store.close()

    store2 = GameStore(db_path)
    assert store2._schema_version == LATEST_VERSION
    assert store2._migration_failed is False
    store2.close()


def test_failing_step_leaves_the_database_usable_and_version_unchanged(root):
    db_path = root / "failing.sqlite3"

    def boom(conn):
        raise RuntimeError("simulated migration bug")

    original = GameStore._MIGRATIONS
    GameStore._MIGRATIONS = (*original, (original[-1][0] + 1, "deliberately broken step", boom))
    try:
        store = GameStore(db_path)
        assert store._schema_version == original[-1][0], "must not advance past the failing step"
        assert store._migration_failed is True
        # the app keeps working on the old shape
        gid = store.insert_game({"played_at": "2099-01-01T00:00:00", "riot_match_id": "z1"}, [])
        assert gid is not None
        store.close()
    finally:
        GameStore._MIGRATIONS = original


TESTS = [
    test_fresh_database_lands_on_latest_version,
    test_old_partial_columns_database_still_completes,
    test_second_launch_is_a_noop,
    test_failing_step_leaves_the_database_usable_and_version_unchanged,
]


def main():
    for test in TESTS:
        root = Path(tempfile.mkdtemp(prefix="vibecheck-schema-"))
        try:
            test(root)
            print(f"  ok  {test.__name__}")
        finally:
            shutil.rmtree(root, ignore_errors=True)
    print("schema migration test OK")


if __name__ == "__main__":
    main()
