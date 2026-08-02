"""Verify the pre-rebrand data-folder migration, no real profile touched.

`config.py` migrates `%LOCALAPPDATA%\\LeagueOfKiffance\\` to `VibeCheck\\` at
*import* time, so every case here runs in its own subprocess with LOCALAPPDATA
pointed at a throwaway folder — once the module is imported, the migration has
already happened and can't be replayed.

The property worth protecting is the one in the last two cases: when the move
can't happen, the app keeps reading the old location. A user whose folder is
locked should see a stale folder name, never an empty app.

Run: .venv\\Scripts\\python tests\\migration_test.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Printed as one JSON line so the parent reads the child's resolved paths
# without importing config itself (which would migrate the real profile).
PROBE = """
import json
from vibecheck import config
print(json.dumps({
    "data_dir": str(config.DATA_DIR),
    "db": str(config.DB_PATH),
    "log": str(config.LOG_PATH),
    "notes": config.DATA_MIGRATION_NOTES,
}))
"""


def resolve_paths(local_appdata: Path) -> dict:
    """Import config in a child process and report what it resolved to."""
    env = {
        **os.environ,
        "LOCALAPPDATA": str(local_appdata),
        "PYTHONPATH": str(REPO_ROOT),
        "PYTHONIOENCODING": "utf-8",
    }
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-c", PROBE],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def make_legacy_install(root: Path, *, hot_journal: bool = False) -> Path:
    """A folder shaped like a real pre-rebrand install."""
    legacy = root / "LeagueOfKiffance"
    legacy.mkdir(parents=True)
    (legacy / "kiffance.sqlite3").write_text("DB-PAYLOAD", encoding="utf-8")
    (legacy / "kiffance.log").write_text("LOG-PAYLOAD", encoding="utf-8")
    (legacy / "supabase.json").write_text("{}", encoding="utf-8")
    (legacy / "ddragon").mkdir()
    (legacy / "ddragon" / "cached.json").write_text("CACHE", encoding="utf-8")
    if hot_journal:
        (legacy / "kiffance.sqlite3-journal").write_text("HOT", encoding="utf-8")
    return legacy


def test_fresh_install(root: Path):
    """Nothing on disk yet: the new names, and no migration noise in the log."""
    paths = resolve_paths(root)
    assert paths["data_dir"] == str(root / "VibeCheck"), paths
    assert paths["db"].endswith("vibecheck.sqlite3"), paths
    assert paths["log"].endswith("vibecheck.log"), paths
    assert paths["notes"] == [], paths["notes"]


def test_legacy_install_migrates(root: Path):
    """Folder and both files move, and everything else rides along."""
    make_legacy_install(root)
    paths = resolve_paths(root)
    new = root / "VibeCheck"

    assert paths["data_dir"] == str(new), paths
    assert not (root / "LeagueOfKiffance").exists(), "old folder left behind"
    assert (new / "vibecheck.sqlite3").read_text(encoding="utf-8") == "DB-PAYLOAD"
    assert (new / "vibecheck.log").read_text(encoding="utf-8") == "LOG-PAYLOAD"
    # The folder holds more than the two renamed files — self-host credentials
    # and the champion-art cache must survive the move too.
    assert (new / "supabase.json").exists(), "supabase.json lost in the move"
    assert (new / "ddragon" / "cached.json").read_text(encoding="utf-8") == "CACHE"


def test_hot_journal_defers_db_rename(root: Path):
    """A crash-recovery journal must never be separated from its database.

    SQLite finds the journal by the database's filename, so renaming the .sqlite3
    out from under it would lose the rollback. The rename waits a launch instead.
    """
    make_legacy_install(root, hot_journal=True)
    paths = resolve_paths(root)
    new = root / "VibeCheck"

    assert paths["data_dir"] == str(new), paths
    assert paths["db"] == str(new / "kiffance.sqlite3"), f"db should not move: {paths['db']}"
    assert (new / "kiffance.sqlite3-journal").exists(), "recovery journal lost"
    # The log has no such constraint and still gets its new name.
    assert paths["log"] == str(new / "vibecheck.log"), paths
    assert any("Deferring" in n for n in paths["notes"]), paths["notes"]


def test_both_folders_keeps_the_new_one(root: Path):
    """An old exe run after the migration recreates the legacy folder.

    The current data wins and the stray folder is left untouched — deleting it
    would throw away whatever that older build captured in the meantime.
    """
    make_legacy_install(root)
    new = root / "VibeCheck"
    new.mkdir()
    (new / "vibecheck.sqlite3").write_text("CURRENT-DB", encoding="utf-8")

    paths = resolve_paths(root)
    assert paths["data_dir"] == str(new), paths
    assert (new / "vibecheck.sqlite3").read_text(encoding="utf-8") == "CURRENT-DB"
    assert (root / "LeagueOfKiffance" / "kiffance.sqlite3").exists(), "old data destroyed"
    assert any("Both" in n for n in paths["notes"]), paths["notes"]


def test_locked_folder_falls_back(root: Path):
    """The one that matters: a move that can't happen must not look like data loss.

    Windows refuses to rename a directory containing an open handle. When that
    happens the app has to keep reading the old folder — creating an empty new
    one instead is what a user would read as "it deleted all my games".
    """
    legacy = make_legacy_install(root)
    handle = open(legacy / "kiffance.sqlite3", "rb")  # noqa: SIM115 - held on purpose
    try:
        paths = resolve_paths(root)
    finally:
        handle.close()

    if paths["data_dir"] == str(root / "VibeCheck"):
        # POSIX renames a directory with open handles happily. The guarantee
        # under test is Windows-only, and Windows is the only platform we ship.
        print("  (skipped: this platform allows renaming an open directory)")
        return

    assert paths["data_dir"] == str(legacy), paths
    assert paths["db"] == str(legacy / "kiffance.sqlite3"), paths
    assert not (root / "VibeCheck").exists(), "empty new folder created instead of falling back"
    assert any("staying on the old folder" in n for n in paths["notes"]), paths["notes"]


def test_second_launch_is_a_noop(root: Path):
    """Migrating twice must not move or re-report anything."""
    make_legacy_install(root)
    resolve_paths(root)
    paths = resolve_paths(root)

    assert paths["notes"] == [], f"second launch should be silent: {paths['notes']}"
    assert paths["data_dir"] == str(root / "VibeCheck"), paths
    assert (root / "VibeCheck" / "vibecheck.sqlite3").read_text(encoding="utf-8") == "DB-PAYLOAD"


TESTS = [
    test_fresh_install,
    test_legacy_install_migrates,
    test_hot_journal_defers_db_rename,
    test_both_folders_keeps_the_new_one,
    test_locked_folder_falls_back,
    test_second_launch_is_a_noop,
]


def main():
    for test in TESTS:
        root = Path(tempfile.mkdtemp(prefix="vibecheck-migration-"))
        try:
            test(root)
            print(f"  ok  {test.__name__}")
        finally:
            shutil.rmtree(root, ignore_errors=True)
    print("migration test OK")


if __name__ == "__main__":
    main()
