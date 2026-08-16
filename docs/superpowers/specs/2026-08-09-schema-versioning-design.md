# Schema versioning + backup-before-migrate

Design for [issue #49](https://github.com/FrairMaxou/vibecheck.lol/issues/49),
the foundation for the Phase 1 data-model work (#50, #51, #52) inside the
visual-overhaul-and-data-model-rework epic (#63).

## Problem

`GameStore._migrate()` only `ALTER`s columns from a fixed list
(`_ADDED_COLUMNS`) and has no notion of a schema version. There is no way to
express an ordered, multi-step migration, and no safety net: a bad step on a
user's database is unrecoverable. ~100 people have live history in it.

## Scope

Structural DDL only, run at app open, must stay fast. No data-heavy rewrite —
that belongs to #50's background pass. `raw_payload` is never touched by this
work, which is what keeps a bad migration recoverable rather than fatal.

## Design

### Migration step registry

```python
_MIGRATIONS: list[tuple[int, str, Callable[[sqlite3.Connection], None]]]
```

Ordered by target version (int), each entry a `(version, description, step_fn)`
tuple. Step 1 wraps the existing `_ADDED_COLUMNS` logic verbatim — it checks
column existence before each `ALTER`, so it stays correct regardless of what
version a mid-migration database claims to be at.

`schema_version` lives in the existing `meta` key/value table — the same
pattern already used for `data_rev`. A missing key means version 0.

At startup, `_migrate()` walks `_MIGRATIONS` in order and runs every step whose
version is greater than the stored `schema_version`.

### Backup

Before running the first pending step of a launch, copy `DB_PATH` to:

```
DATA_DIR/backups/<timestamp>-schema-v<target_version>
```

This mirrors the convention `tools/reset_data.py` already uses
(`DATA_DIR / "backups" / <timestamp>`). One backup per launch attempt, not per
step.

Accepted cost: with the "retry every launch" failure policy below, a
persistently-failing step produces a new backup on every launch until it's
fixed. Backups are DB-file-sized (currently ~1.5 MB across 41 games) and
failures are meant to be rare and always logged loudly, so unbounded backup
growth is not worth guarding against in this pass.

### Execution and failure path

Each step runs inside its own `with self._db:` transaction:

1. Run the step function against the connection.
2. On success: write the new `schema_version` to `meta`, which commits with
   the same transaction (SQLite's context-manager commit-on-success).
3. On exception: the `with` block rolls back automatically. The exception is
   caught, logged loudly with the step's description and the exception detail,
   and no further steps run this launch. `schema_version` is left at its prior
   value. The app continues starting up normally on the old, still fully
   functional schema shape.

**Retry policy: retry every launch.** No "already failed, skip" bookkeeping.
Since `schema_version` was never bumped, a failed attempt is indistinguishable
from "never tried" — the next launch just tries again, which lets a transient
failure (e.g. disk full at that instant) self-heal without any extra state to
manage or get stuck.

### Telemetry addition

`telemetry.py::_payload()` gains two fields:

- `schema_version: int` — always sent.
- `schema_migration_failed: bool` — true if a migration step failed during
  this session's startup.

This is the only feedback loop available on ~100 machines the maintainer
cannot otherwise inspect, so a migration failure should be visible in
aggregate, not only in an individual user's local log file.

**Deploy ordering (real production step, not just code):** the live Supabase
`telemetry_pings` table needs an additive column *before* a build that sends
these fields ships, or every ping from that build fails. Add to
`supabase/telemetry.sql` (safe to re-run, per its existing header comment):

```sql
alter table telemetry_pings add column if not exists schema_version int;
alter table telemetry_pings add column if not exists schema_migration_failed boolean;
```

Run this in Supabase Studio's SQL editor *before* merging/releasing the code
change. This is a manual step in the same category as the other Supabase items
in `docs/SECURITY.md`'s pre-release checklist.

### Testing

New `tests/schema_migration_test.py`, following the standalone-script pattern
already used by `tests/migration_test.py` and `tests/smoke_test.py` (a `TESTS`
list of functions, run via `.venv\Scripts\python tests\schema_migration_test.py`,
no pytest dependency).

Cases:

- A fixture database in the pre-migration shape migrates cleanly and its
  content is byte-identical afterward (per the issue's done-when).
- A deliberately-failing step leaves the database usable, `schema_version`
  unchanged, and a backup file present.
- A second launch after a successful migration is a no-op: no duplicate
  backup, no steps re-run.
- A database already carrying some (but not all) of the old `_ADDED_COLUMNS`
  still completes correctly — the pre-existing partial-migration case the
  issue calls out explicitly.

## Risk, most severe first

1. **A bad step corrupts real history for ~100 users.** Mitigated by:
   backup-before-first-DDL, the byte-identical fixture test, and the
   structural-DDL-only scope (no `raw_payload` rewrite, so a bad normalize
   downstream in #50 stays re-runnable rather than fatal).
2. **Startup hangs on a large history.** Excluded by scope: this issue is
   structural DDL only. Any data-heavy work is explicitly deferred to #50's
   background pass.
3. **The telemetry payload change ships before the Supabase column exists,**
   breaking the daily ping for every install on that build. Mitigated by
   sequencing: run the `telemetry.sql` addition in Studio first, merge the
   code second — called out explicitly above so it isn't missed at release
   time.

## Out of scope

- Normalizing participants/items/augments (#50).
- Compressing `raw_payload` (#51).
- Achievement progress tables (#52).
- Backup retention/pruning — not needed yet at this schema-bump frequency;
  revisit if Phase 1's four issues each bump the version and backups
  accumulate visibly.
