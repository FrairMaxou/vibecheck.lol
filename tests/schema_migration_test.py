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


def test_pending_migration_backs_up_the_database_first(root):
    db_path = root / "backup-me.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE games (id INTEGER PRIMARY KEY, riot_match_id TEXT UNIQUE,
                             played_at TEXT NOT NULL);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.commit()
    conn.close()
    pre_migration_bytes = db_path.read_bytes()

    store = GameStore(db_path)
    store.close()

    backups = list((root / "backups").glob(f"*-schema-v{LATEST_VERSION}.sqlite3"))
    assert len(backups) == 1, backups
    assert backups[0].read_bytes() == pre_migration_bytes, (
        "backup must hold the pre-migration content"
    )


def test_up_to_date_database_creates_no_further_backup(root):
    db_path = root / "no-backup-needed.sqlite3"
    # First open starts at schema_version 0 (even a brand-new db), so v1 is
    # pending and this one DOES back up — that backup is what's under test in
    # test_pending_migration_backs_up_the_database_first above.
    GameStore(db_path).close()
    backups_dir = root / "backups"
    count_after_first_open = len(list(backups_dir.iterdir()))

    # Second open: schema_version is already LATEST_VERSION, nothing pending.
    GameStore(db_path).close()
    assert len(list(backups_dir.iterdir())) == count_after_first_open, (
        "a database already on the latest version must not accumulate backups"
    )


def test_persistently_failing_step_backs_up_on_every_launch(root):
    db_path = root / "retry.sqlite3"

    def boom(conn):
        raise RuntimeError("simulated migration bug")

    original = GameStore._MIGRATIONS
    GameStore._MIGRATIONS = (*original, (original[-1][0] + 1, "deliberately broken step", boom))
    try:
        GameStore(db_path).close()
        GameStore(db_path).close()
        backups = list((root / "backups").glob(f"*-schema-v{original[-1][0] + 1}.sqlite3"))
        assert len(backups) == 2, "retry-every-launch means a fresh backup each attempt"
    finally:
        GameStore._MIGRATIONS = original


def test_backup_failure_skips_migration_this_launch(root):
    """If backup fails (disk full, permissions, etc.), the database must not be
    migrated unprotected this launch. Schema version stays on the pre-migration
    value and no DDL step runs.
    """
    db_path = root / "no-backup.sqlite3"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE games (id INTEGER PRIMARY KEY, riot_match_id TEXT UNIQUE,
                             played_at TEXT NOT NULL);
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    conn.commit()
    conn.close()

    original_backup = GameStore._backup_before_migration

    def failing_backup(self, target_version):
        # Simulate a backup failure (disk full, permission denied, etc.)
        raise OSError("Simulated backup failure")

    GameStore._backup_before_migration = failing_backup
    try:
        store = GameStore(db_path)
        # Despite the failed backup, the store should be usable on the old version
        assert store._schema_version == 0, "must stay on pre-migration version"
        assert store._migration_failed is True, "must flag that migration was skipped"
        # The games table must not have been altered by the v1 migration step
        cols = {r["name"] for r in store._db.execute("PRAGMA table_info(games)")}
        assert "enemy_champions" not in cols, "v1 migration must not have run when backup failed"
        store.close()
    finally:
        GameStore._backup_before_migration = original_backup


TESTS = [
    test_fresh_database_lands_on_latest_version,
    test_old_partial_columns_database_still_completes,
    test_second_launch_is_a_noop,
    test_failing_step_leaves_the_database_usable_and_version_unchanged,
    test_pending_migration_backs_up_the_database_first,
    test_up_to_date_database_creates_no_further_backup,
    test_persistently_failing_step_backs_up_on_every_launch,
    test_backup_failure_skips_migration_this_launch,
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
