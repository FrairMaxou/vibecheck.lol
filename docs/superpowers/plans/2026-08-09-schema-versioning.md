# Schema Versioning + Backup-Before-Migrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give `GameStore` a real, versioned migration framework — ordered steps, one transaction each, a backup of the database taken before the first DDL of any pending migration, and failure isolation that keeps the app running on the last-known-good schema — replacing the current fixed-column-list `_migrate()`.

**Architecture:** A module-level tuple of `(target_version, description, step_fn)` entries drives `GameStore._migrate()`. `schema_version` is tracked in the existing `meta` key/value table. Each pending step runs in its own lock+transaction; a step that raises rolls back automatically (SQLite's commit-on-success context manager) and is logged, leaving `schema_version` untouched and the app fully functional on the prior shape. A file copy of the database is taken once per launch, before the first pending step runs. `telemetry.py` gains two additive fields so migration health is visible in aggregate.

**Tech Stack:** Python stdlib only — `sqlite3`, `shutil`, `datetime`. No new dependency.

## Global Constraints

- Structural DDL only, run at app open — must stay fast. No data-heavy rewrite (that's issue #50's background pass).
- `raw_payload` is never touched by this work.
- Retry policy: retry every launch, no backoff/skip bookkeeping — a failed attempt is indistinguishable from "never tried" since `schema_version` was never bumped.
- One backup per launch attempt (not per step), at `<db_path.parent>/backups/<timestamp>-schema-v<target>.sqlite3`, mirroring the naming convention already used by `tools/reset_data.py`.
- A migration step must never crash the app — catch broadly, log loudly (`log.exception`), keep running on the old schema.
- No helper method that acquires `self._lock` (`get_meta`, `set_meta`, etc.) may be called from inside a block that already holds it — `threading.Lock` is not reentrant. Schema-version writes inside a step's transaction use a direct `self._db.execute(...)`, never `self.set_meta(...)`.
- The Supabase `telemetry_pings` table needs its two new columns added in Studio (`supabase/telemetry.sql`) **before** a build sending them ships — additive/backward-compatible per the project's standing Supabase rule, but sequencing still matters or every ping from that build starts failing.
- Comments explain the non-obvious *why*, not the what (project convention).
- Conventional Commits on every commit (enforced by a local hook).

---

### Task 1: Versioned migration framework (no backup yet)

**Files:**
- Modify: `vibecheck/store.py:1-115` (imports, module-level step function, `GameStore.__init__`, replace `_ADDED_COLUMNS`/`_migrate`)
- Create: `tests/schema_migration_test.py`

**Interfaces:**
- Produces: `GameStore._MIGRATIONS: tuple[tuple[int, str, Callable[[sqlite3.Connection], None]], ...]` (module-level step registry, class attribute)
- Produces: `GameStore._read_schema_version() -> int`
- Produces: `GameStore._migrate() -> None` (same name/signature as today, called from `__init__` exactly where the old one was)
- Produces: `GameStore._db_path: Path` (new instance attribute, the path passed to `__init__`)
- Produces: `GameStore._schema_version: int` and `GameStore._migration_failed: bool` (new instance attributes, set by `_migrate()`)

- [ ] **Step 1: Write the failing tests**

Create `tests/schema_migration_test.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv\Scripts\python tests\schema_migration_test.py`
Expected: `ImportError` or `AttributeError` — `GameStore._MIGRATIONS` doesn't exist yet.

- [ ] **Step 3: Replace the fixed-column migration with the versioned framework**

In `vibecheck/store.py`, add `from collections.abc import Callable` to the imports at the top (alongside the existing `import sqlite3` etc.).

Add this module-level function **above** `class GameStore:` (it's referenced by the class body below):

```python
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
```

Replace lines 86–115 (the `__init__`, `_ADDED_COLUMNS`, `_JSON_COLUMNS`, and `_migrate`) with:

```python
class GameStore:
    def __init__(self, db_path: Path = DB_PATH):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db_path = db_path
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(_SCHEMA)
        self._migrate()
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
    )
    # Fields stored as JSON arrays.
    _JSON_COLUMNS = ("enemy_champions", "augments", "items")

    def _read_schema_version(self) -> int:
        value = self.get_meta("schema_version")
        return int(value) if value else 0

    def _migrate(self) -> None:
        current = self._read_schema_version()
        pending = [step for step in self._MIGRATIONS if step[0] > current]
        self._schema_version = current
        self._migration_failed = False
        if not pending:
            return

        for version, description, step_fn in pending:
            try:
                with self._lock, self._db:
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
            current = version
            self._schema_version = current
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python tests\schema_migration_test.py`
Expected: all four tests print `ok` and the script prints `schema migration test OK`.

- [ ] **Step 5: Run the existing suites to check for regressions**

Run:
```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\achievement_test.py
```
Expected: both print their `OK` line — `_ADDED_COLUMNS`/`_migrate` are gone, and nothing else in the codebase referenced them (verified: they were private and used only inside `store.py`).

- [ ] **Step 6: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git add vibecheck/store.py tests/schema_migration_test.py
git commit -m "feat(store): version the schema with an ordered migration framework"
```

---

### Task 2: Backup before the first pending migration

**Files:**
- Modify: `vibecheck/store.py` (add `import shutil`, `from datetime import datetime` already present; add `_backup_before_migration`, call it from `_migrate`)
- Modify: `tests/schema_migration_test.py` (add backup-focused tests)

**Interfaces:**
- Consumes: `GameStore._db_path` (Task 1), `GameStore._MIGRATIONS` (Task 1)
- Produces: `GameStore._backup_before_migration(target_version: int) -> None`

- [ ] **Step 1: Write the failing tests**

Add to `tests/schema_migration_test.py`, above the `TESTS` list:

```python
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
```

Add the three new functions to the `TESTS` list.

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run: `.venv\Scripts\python tests\schema_migration_test.py`
Expected: `test_pending_migration_backs_up_the_database_first` and `test_persistently_failing_step_backs_up_on_every_launch` fail with an assertion (no `backups/` directory created yet). `test_up_to_date_database_creates_no_further_backup` passes trivially (both counts are 0) — that's fine, it becomes a real regression guard once backups exist.

- [ ] **Step 3: Implement the backup step**

Add `import shutil` to the top of `vibecheck/store.py`.

Add this method to `GameStore` (near `_migrate`):

```python
def _backup_before_migration(self, target_version: int) -> None:
    """Copy the database into <data dir>/backups/ before the first DDL of a
    new schema version — the safety net for ~100 users' live history if a
    step turns out to be wrong. Mirrors the naming tools/reset_data.py
    already uses for its own timestamped backups.
    """
    backups_dir = self._db_path.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups_dir / f"{timestamp}-schema-v{target_version}.sqlite3"
    shutil.copy2(self._db_path, dest)
    log.info("Backed up database to %s before migrating to schema v%d", dest, target_version)
```

Update `_migrate` to call it before the step loop, and to treat a backup failure the same as a step failure (skip migrating this launch rather than proceed unprotected):

```python
def _migrate(self) -> None:
    current = self._read_schema_version()
    pending = [step for step in self._MIGRATIONS if step[0] > current]
    self._schema_version = current
    self._migration_failed = False
    if not pending:
        return

    target_version = pending[-1][0]
    try:
        self._backup_before_migration(target_version)
    except OSError:
        log.exception(
            "Could not back up the database before migrating to v%d; skipping migration this launch",
            target_version,
        )
        self._migration_failed = True
        return

    for version, description, step_fn in pending:
        try:
            with self._lock, self._db:
                step_fn(self._db)
                self._db.execute(
                    "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (str(version),),
                )
        except Exception:
            log.exception(
                "Schema migration to v%d (%s) failed; staying on v%d",
                version,
                description,
                self._schema_version,
            )
            self._migration_failed = True
            return
        current = version
        self._schema_version = current
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv\Scripts\python tests\schema_migration_test.py`
Expected: all seven tests print `ok`.

- [ ] **Step 5: Run the existing suites to check for regressions**

```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\achievement_test.py
```
Expected: both pass — `smoke_test.py` and `achievement_test.py` each construct fresh `GameStore`s in temp dirs, so they now also produce a `backups/` folder as a side effect on a fresh install; confirm neither test asserts on the temp directory's exact contents (it doesn't — both only touch the `.sqlite3` file's own path).

- [ ] **Step 6: Lint and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
git add vibecheck/store.py tests/schema_migration_test.py
git commit -m "feat(store): back up the database before the first pending migration"
```

---

### Task 3: Telemetry visibility into migration failures

**Files:**
- Modify: `vibecheck/store.py` (add two public getters)
- Modify: `vibecheck/telemetry.py:68-86` (`_payload`)
- Modify: `supabase/telemetry.sql` (additive columns)
- Modify: `tests/schema_migration_test.py` (payload test)

**Interfaces:**
- Consumes: `GameStore._schema_version`, `GameStore._migration_failed` (Task 1/2)
- Produces: `GameStore.schema_version() -> int`
- Produces: `GameStore.schema_migration_failed() -> bool`

- [ ] **Step 1: Write the failing test**

Add to `tests/schema_migration_test.py`, add the import `from vibecheck import telemetry` near the top (with the other `vibecheck` imports), and add this test above `TESTS`:

```python
def test_telemetry_payload_carries_schema_health(root):
    store = GameStore(root / "telemetry.sqlite3")
    payload = telemetry._payload(store)
    assert payload["schema_version"] == LATEST_VERSION, payload
    assert payload["schema_migration_failed"] is False, payload
    store.close()
```

Add `test_telemetry_payload_carries_schema_health` to `TESTS`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv\Scripts\python tests\schema_migration_test.py`
Expected: `AttributeError: 'GameStore' object has no attribute 'schema_version'`.

- [ ] **Step 3: Add the public getters to GameStore**

Add these two methods to `vibecheck/store.py`, near `_migrate`:

```python
def schema_version(self) -> int:
    """Current schema version, after whatever migration ran at open."""
    return self._schema_version


def schema_migration_failed(self) -> bool:
    """Whether the most recent startup's migration attempt failed, leaving
    the database on an older version than the code expects.
    """
    return self._migration_failed
```

- [ ] **Step 4: Wire the fields into the telemetry payload**

In `vibecheck/telemetry.py`, add two keys to the dict returned by `_payload` (after `"squad_enabled"`):

```python
        "squad_enabled": bool(load_config()),
        "schema_version": store.schema_version(),
        "schema_migration_failed": store.schema_migration_failed(),
    }
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv\Scripts\python tests\schema_migration_test.py`
Expected: all eight tests print `ok`.

- [ ] **Step 6: Add the additive Supabase columns**

Append to the end of `supabase/telemetry.sql`:

```sql
-- Added for issue #49 (schema versioning). Additive and nullable, so a build
-- older than this keeps posting successfully — these two columns are simply
-- null for it. Deploy this file in Studio BEFORE releasing the app version
-- that starts sending these fields, or every ping from that build 400s.
alter table telemetry_pings add column if not exists schema_version int;
alter table telemetry_pings add column if not exists schema_migration_failed boolean;
```

This step is a note for the maintainer, not something CI runs — flag it clearly in the PR description as a manual pre-release action (Supabase Studio → SQL Editor → run the appended block), matching the existing pattern in `docs/SECURITY.md`'s checklist.

- [ ] **Step 7: Run the full existing suite**

```powershell
.venv\Scripts\python tests\smoke_test.py
.venv\Scripts\python tests\migration_test.py
.venv\Scripts\python tests\achievement_test.py
.venv\Scripts\python tests\schema_migration_test.py
```
Expected: every script prints its `OK` line.

- [ ] **Step 8: Lint, pre-commit, and commit**

```powershell
.venv\Scripts\ruff check . --fix
.venv\Scripts\ruff format .
.venv\Scripts\pre-commit run --all-files
git add vibecheck/store.py vibecheck/telemetry.py supabase/telemetry.sql tests/schema_migration_test.py
git commit -m "feat(telemetry): report schema version and migration failures"
```

---

## Final check before opening the PR

- [ ] Re-read `docs/superpowers/specs/2026-08-09-schema-versioning-design.md` against the three commits above — confirm every design section has a corresponding change.
- [ ] `.venv\Scripts\pre-commit run --all-files` clean.
- [ ] PR description calls out the Supabase manual step (Task 3, Step 6) explicitly, since CI cannot verify it ran.
- [ ] PR description notes this is Phase 1 foundation work for #63 and that #50/#51/#52 build on `_MIGRATIONS`.
