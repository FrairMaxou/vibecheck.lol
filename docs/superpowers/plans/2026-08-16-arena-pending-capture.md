# Arena Two-Phase Capture (#96) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop silently losing Arena games. Ask the "Had fun?" rating the moment the player's own game ends, and fill in the real stats asynchronously once the League client's match history actually has them.

**Architecture:** Riot's local match-history cache can take anywhere from ~3 to ~10+ minutes to include an Arena game after the player's own gameflow phase reaches `PreEndOfGame` (measured live on two real games: 597687660 and 597690405 — see Root Cause below). VibeCheck's existing 30s retry (`_capture_game`'s match-history fallback) is far too short for that, and the existing catch-up sweep only re-checks on the next lobby visit or client reconnect, which can arrive after the game has scrolled out of relevance. The fix is two-phase: (1) capture the game's real id from the live gameflow session the instant the game ends, insert a minimal "pending" row, and show the rating popup immediately — this also replaces the old "guess the newest entry in `recent_matches()`" heuristic, which is the actual root cause of #96, not just a too-short timeout; (2) resolve that pending row later by looking up `match_details(known_id)` directly — a targeted id lookup, not a list scan — on a bounded interval, piggybacked onto the existing catch-up triggers plus a new sparse timer so it doesn't depend on the player queuing again soon.

**Tech Stack:** Python, stdlib `sqlite3`, `requests` (LCU REST via `vibecheck/lcu.py`), Tk (rating popup).

**Spec:** No separate spec doc. This plan's Architecture section is the design record — derived from a live-debugging session against GitHub issue #96, building on the diagnostic groundwork in commit `261ebbb` ("fix(capture): add diagnostic logging for silent Arena capture failures (#96)"). PRD.md F6/F7 are updated in Task 6 to reflect the new pending-resolution behavior.

## Root Cause (evidence gathered this session)

1. The player's own gameflow phase already advances to `PreEndOfGame` **the instant they're eliminated** in Arena — confirmed twice live (11:01:16 phase change while `game_client_running` was still `True`; the client itself didn't close until 4s later). So the existing capture trigger (`END_PHASES = {"PreEndOfGame", "EndOfGame"}`) is correct and does not need to change.
2. `_fresh_match_from_history()` guesses the "newest" game via `recent_matches()`'s top-N list. For Arena, the just-finished game does not appear in that list for a long, *variable* time after step 1 — measured live at **~10 min** (game 597687660) and **~3.5 min** (game 597690405). The variance tracks how long the rest of the match kept running after the player's own elimination, not a fixed client-side cache delay.
3. `_capture_game()`'s match-history retry is `attempts=10, interval=3.0` (30s total) — far shorter than either measurement — so it always exhausts, logs `"Game ended but neither stats nor match history yielded it"`, and the game is dropped. Reproduced twice live, byte-for-byte identical failure both times.
4. The existing safety net, `_catch_up()`, only re-scans on `IDLE_PHASES` transitions (`None`/`Lobby`) and client reconnect. In the live repro, the player queued into a new game before the next such transition happened, so the missed game sat unresolved until this session force-restarted the app to trigger a fresh catch-up sweep at connect time.
5. The live gameflow session (`GET /lol-gameflow/v1/session`) exposes `gameData.gameId` — the *authoritative* id for the game that's ending — reliably at the moment `PreEndOfGame` fires (confirmed live). Looking this up directly via `match_details(id)` instead of guessing from `recent_matches()` sidesteps the root cause entirely, for every queue type, not just Arena.

## Global Constraints

- No busy-polling against the LCU (PRD §6b N1): the new resolution timer only touches the LCU when the local store actually has an unresolved row, and runs on a 5-minute interval, not tight polling.
- Feature code never issues SQL directly — all schema/queries stay inside `vibecheck/store.py` (PRD §11).
- A migration step must never crash the app or lose existing data — follow the existing `_MIGRATIONS` pattern (backup-before-migrate, per-step transaction, `_migration_failed` flag) exactly.
- The rating popup must never appear during live gameplay (F10b) — the pending popup only fires from the same `END_PHASES`-triggered path the existing popup already uses.
- UI language is English; no new user-facing strings beyond a short popup subtitle for the pending case.

---

## Known limitation (documented, not silently accepted)

A pending row is inserted with `played_at = now()` (the moment the player's game ends), because the real `gameCreation` timestamp isn't known until resolution. Session grouping (`session_id` / `game_index_in_session`) is computed once, at insert time, from that estimate, and is **not** retroactively recomputed once the real timestamp arrives at resolution — only the `played_at` column itself is corrected for display/sort order.

**Correction (found in final review, original estimate below was wrong):** every other row's `played_at` is `gameCreation` — the game's *start* time — but a pending stub's `played_at` is `now()` at the game's *end*. `_session_for()`'s gap is computed against that estimate, so the stub's computed gap is inflated by the *entire game duration* (~20-25 minutes for Arena), not just the resolution lag. Against `SESSION_GAP_SECONDS` (3600s / 1h), the real safety margin is roughly 35 minutes, not the ~50 minutes (10 min lag vs 60 min threshold) originally claimed here — about 1.7x headroom, not 6x. This can still misplace a session boundary without any second game being involved at all, whenever a single Arena game plus its resolution lag runs close to an hour. Impact remains scoped to dashboard session grouping (cosmetic), never data or rating loss. Accepted for this fix; a follow-up could recompute session assignment in `complete_game` from the real `played_at` (safe in the common case where the completed row is still the newest row in `games`) if this proves to matter in practice.

---

### Task 1: Schema migration v2 — `resolved` and `pending_premades` columns

**Files:**
- Modify: `vibecheck/store.py:164-170` (`_MIGRATIONS` tuple), and add a new step function near `_step_v1_added_columns` (`vibecheck/store.py:94-112`)
- Modify: `tests/schema_migration_test.py` (add one test, mirroring `test_old_partial_columns_database_still_completes`)

**Interfaces:**
- Produces: `games.resolved` (INTEGER, 0 = pending stats, 1 = complete — default 1 so every existing row is unaffected), `games.pending_premades` (TEXT, JSON array of puuids, NULL once resolved or for normal games)

- [ ] **Step 1: Write the failing test**

Add to `tests/schema_migration_test.py`, in the same style as `test_old_partial_columns_database_still_completes`:

```python
def test_v2_adds_pending_capture_columns(root):
    store = GameStore(root / "v2.sqlite3")
    cols = {r["name"] for r in store._db.execute("PRAGMA table_info(games)")}
    assert {"resolved", "pending_premades"} <= cols, cols
    row = store._db.execute(
        "INSERT INTO games (riot_match_id, played_at) VALUES ('v2-1', '2099-01-01T00:00:00') "
        "RETURNING resolved, pending_premades"
    ).fetchone()
    assert row["resolved"] == 1, "existing/normal rows must default to resolved"
    assert row["pending_premades"] is None
    store.close()
```

Add `test_v2_adds_pending_capture_columns` to the `TESTS` list at the bottom of the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python tests\schema_migration_test.py`
Expected: FAIL — `resolved`/`pending_premades` not in `cols` (column doesn't exist yet).

- [ ] **Step 3: Write minimal implementation**

In `vibecheck/store.py`, add a new migration step function right after `_step_v1_added_columns` (after line 112):

```python
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
```

Add it to `_MIGRATIONS` (`vibecheck/store.py:164-170`):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python tests\schema_migration_test.py`
Expected: PASS — `schema migration test OK`, all existing tests in the file still pass unchanged (they reference `_MIGRATIONS[-1][0]` dynamically, so v2 doesn't break them).

- [ ] **Step 5: Commit**

```bash
git add vibecheck/store.py tests/schema_migration_test.py
git commit -m "feat(store): add schema v2 for pending Arena capture (#96)"
```

---

### Task 2: Store methods — insert/resolve pending games, hide stubs from dashboard views

**Files:**
- Modify: `vibecheck/store.py:281-337` (near `insert_game`) — add `insert_pending_game`, `complete_game`, `unresolved_games`
- Modify: `vibecheck/store.py:523-536` (`recent_games`) and `:538-584` (`games_with_details`) — filter to `resolved = 1`
- Create: `tests/pending_capture_test.py`

**Interfaces:**
- Consumes: `GameStore._session_for(played_at: str) -> tuple[int, int]` (existing private helper, `vibecheck/store.py:622-639`)
- Produces:
  - `insert_pending_game(riot_match_id: str, played_at: str, premade_puuids: set) -> int | None`
  - `complete_game(game_id: int, game: dict, teammates: list) -> bool`
  - `unresolved_games() -> list[dict]` — rows with `resolved = 0`, each dict includes `id`, `riot_match_id`, `pending_premades`

- [ ] **Step 1: Write the failing test**

Create `tests/pending_capture_test.py`:

```python
"""Two-phase Arena capture: pending stub -> resolved game (issue #96).

Run: .venv\\Scripts\\python tests\\pending_capture_test.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vibecheck import capture
from vibecheck.store import GameStore

MY_PUUID = "me-1234"

FAKE_ARENA_MATCH = {
    "gameId": 597690405,
    "gameCreation": 1786844317780,
    "gameDuration": 1310,
    "queueId": 1750,
    "participants": [
        {
            "participantId": 1,
            "teamId": 100,
            "championId": 79,
            "playerSubteamId": 3,
            "timeline": {"lane": "NONE"},
            "stats": {"win": False, "kills": 4, "deaths": 6, "assists": 5, "totalMinionsKilled": 20},
        },
        {
            "participantId": 2,
            "teamId": 100,
            "championId": 34,
            "playerSubteamId": 3,
            "stats": {"win": False, "kills": 2, "deaths": 4, "assists": 3},
        },
    ],
    "participantIdentities": [
        {"participantId": 1, "player": {"puuid": MY_PUUID, "gameName": "Maxime"}},
        {"participantId": 2, "player": {"puuid": "friend-1", "gameName": "Alex"}},
    ],
}


def test_pending_row_rateable_before_resolution():
    with tempfile.TemporaryDirectory() as tmp:
        store = GameStore(Path(tmp) / "pending.sqlite3")
        stored_id = store.insert_pending_game("597690405", "2026-08-16T11:01:16", {"friend-1"})
        assert stored_id is not None

        # rateable immediately, like any other game
        store.set_rating(stored_id, 4)

        # not yet in the dashboard's game list — stats aren't real yet
        assert store.games_with_details() == []
        assert store.recent_games() == []

        # but it does exist, so a duplicate PreEndOfGame/EndOfGame fire is a no-op
        assert store.has_game("597690405")
        assert store.insert_pending_game("597690405", "2026-08-16T11:01:16", set()) is None

        unresolved = store.unresolved_games()
        assert len(unresolved) == 1 and unresolved[0]["id"] == stored_id
        assert json.loads(unresolved[0]["pending_premades"]) == ["friend-1"]
        store.close()


def test_complete_game_fills_stats_and_keeps_the_rating():
    with tempfile.TemporaryDirectory() as tmp:
        store = GameStore(Path(tmp) / "complete.sqlite3")
        stored_id = store.insert_pending_game("597690405", "2026-08-16T11:01:16", {"friend-1"})
        store.set_rating(stored_id, 4)

        result = capture.normalize_match(FAKE_ARENA_MATCH, MY_PUUID, {79: "Gragas", 34: "Anivia"}, {"friend-1"})
        assert store.complete_game(stored_id, result["game"], result["teammates"]) is True

        assert store.unresolved_games() == []
        rows = store.games_with_details()
        assert len(rows) == 1
        row = rows[0]
        assert row["id"] == stored_id
        assert row["champion"] == "Gragas"
        assert row["fun_score"] == 4, "rating given at pending-time must survive completion"
        assert [t["name"] for t in row["teammates"]] == ["Alex"]

        # resolving twice is a safe no-op, not a duplicate/crash
        assert store.complete_game(stored_id, result["game"], result["teammates"]) is False
        store.close()


TESTS = [
    test_pending_row_rateable_before_resolution,
    test_complete_game_fills_stats_and_keeps_the_rating,
]


def main():
    for test in TESTS:
        test()
        print(f"  ok  {test.__name__}")
    print("pending capture test OK")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python tests\pending_capture_test.py`
Expected: FAIL — `AttributeError: 'GameStore' object has no attribute 'insert_pending_game'`

- [ ] **Step 3: Write minimal implementation**

In `vibecheck/store.py`, add these methods right after `insert_game` (after line 337):

```python
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
                "SELECT id, riot_match_id, pending_premades FROM games WHERE resolved = 0"
            ).fetchall()
        return [dict(r) for r in rows]
```

Then filter the two dashboard-facing read queries so stub rows stay invisible until resolved — `recent_games()` (`vibecheck/store.py:523-536`):

```python
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
```

And `games_with_details()` (`vibecheck/store.py:538-584`) — add `WHERE g.resolved = 1` to its `games` query:

```python
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
```

(The `mates`/`tags` queries below it are unaffected — they're only ever looked up for ids present in `games`, which no longer include unresolved stubs.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv\Scripts\python tests\pending_capture_test.py`
Expected: PASS — `pending capture test OK`

Also re-run the full existing suite to confirm nothing regressed:
Run: `.venv\Scripts\python tests\smoke_test.py && .venv\Scripts\python tests\schema_migration_test.py && .venv\Scripts\python tests\achievement_test.py`
Expected: all three print their `OK` line.

- [ ] **Step 5: Commit**

```bash
git add vibecheck/store.py tests/pending_capture_test.py
git commit -m "feat(store): pending-game insert/resolve for two-phase Arena capture (#96)"
```

---

### Task 3: LCU client — expose the live gameflow session

**Files:**
- Modify: `vibecheck/lcu.py:112-114` (next to `end_of_game_stats`)

**Interfaces:**
- Produces: `LcuClient.gameflow_session() -> dict | None`

- [ ] **Step 1: Write the failing test**

This is a one-line, direct pass-through of an already-tested pattern (`get()` is covered indirectly by every other `LcuClient` method; there's no live-LCU test harness in this codebase — `lcu.py` has no dedicated test file today, consistent with it being a thin, mostly-untestable-offline adapter). Skip to implementation; verify by the manual check in Step 2.

- [ ] **Step 2: Write the implementation**

In `vibecheck/lcu.py`, right after `end_of_game_stats` (line 112-113):

```python
    def end_of_game_stats(self):
        return self.get("/lol-end-of-game/v1/eol-game-data")

    def gameflow_session(self):
        """The live gameflow session, including gameData.gameId — the
        authoritative id for the game that just ended (issue #96). Available
        immediately after PreEndOfGame fires, before Riot's local
        match-history cache has synced it (which can take minutes for
        Arena).
        """
        return self.get("/lol-gameflow/v1/session")
```

- [ ] **Step 3: Verify manually**

Run (League client must be open):

```powershell
.venv\Scripts\python.exe -c "from vibecheck import lcu; c = lcu.LcuClient(lcu.discover()); print(c.gameflow_session())"
```

Expected: a dict (or `None` if no client running) — no exception. This mirrors the exact call already exercised live in this session's debugging (`tools/lcu_monitor.py` uses the same `/lol-gameflow/v1/session` path).

- [ ] **Step 4: Commit**

```bash
git add vibecheck/lcu.py
git commit -m "feat(lcu): expose the live gameflow session (#96)"
```

---

### Task 4: app.py — capture the known game id, stop guessing via recent_matches

**Files:**
- Modify: `vibecheck/app.py:527-553` (`_capture_game`)
- Modify: `vibecheck/app.py:673-680` area — add `_known_game_id` near `_already_captured`

**Interfaces:**
- Consumes: `LcuClient.gameflow_session()` (Task 3), `LcuClient.match_details(game_id: int)` (existing, `vibecheck/lcu.py:131-133`)
- Produces: `App._known_game_id(self) -> int | None`; `_capture_game` now falls through to `self._create_pending_capture(known_game_id)` (Task 5) instead of only warning

- [ ] **Step 1: Write the implementation**

Add `_known_game_id` in `vibecheck/app.py`, right before `_capture_game` (before line 527):

```python
    def _known_game_id(self) -> int | None:
        """The authoritative id for the game that's ending, straight from the
        live gameflow session (issue #96) — available immediately after
        PreEndOfGame/EndOfGame, well before Riot's local match-history cache
        has synced it. Using this instead of guessing the "newest" entry in
        recent_matches() is what makes the match-history lookup exact rather
        than order- and timing-dependent, which is what actually broke Arena
        capture (a stale "newest" id can win for the entire retry window).
        """
        if self._client is None:
            return None
        session = self._client.gameflow_session() or {}
        game_id = (session.get("gameData") or {}).get("gameId")
        return game_id if isinstance(game_id, int) and game_id > 0 else None
```

Replace `_capture_game` (`vibecheck/app.py:527-553`) with:

```python
    def _capture_game(self) -> None:
        known_game_id = self._known_game_id()

        # Primary source: the end-of-game stats endpoint (has premade/party info).
        eol = self._await(self._client.end_of_game_stats, attempts=6, label="end_of_game_stats")
        if eol is not None:
            game_id_str = str(eol.get("gameId", ""))
            if self._already_captured(game_id_str):
                return
            result = capture.normalize(
                eol, self._my_puuid, self._champ_names, self._premade_puuids, self._assets
            )
            self._finish_capture(game_id_str, result, source="end-of-game stats")
            return

        # Fallback: the client's own match history. Look it up by the id we
        # already know from the live gameflow session when we have one —
        # exact, not a guess — falling back to the old "newest in
        # recent_matches()" heuristic only if that id is somehow unavailable.
        log.info("End-of-game stats unavailable; falling back to match history")
        if known_game_id is not None:
            match = self._await(
                lambda: self._client.match_details(known_game_id),
                attempts=10,
                interval=3.0,
                label="match_history",
            )
        else:
            match = self._await(
                self._fresh_match_from_history, attempts=10, interval=3.0, label="match_history"
            )
        if match is not None:
            game_id_str = str(match.get("gameId", ""))
            result = capture.normalize_match(
                match, self._my_puuid, self._champ_names, self._premade_puuids, self._assets
            )
            self._finish_capture(game_id_str, result, source="match history")
            return

        if known_game_id is None:
            log.warning("Game ended but neither stats nor match history yielded it")
            return

        # Match history hasn't synced yet — measured 3-10+ minutes for Arena
        # (#96), well past any reasonable live retry window. Ask for the
        # rating now, while it's fresh, and resolve the real stats
        # asynchronously once the client's history catches up.
        self._create_pending_capture(known_game_id)
```

- [ ] **Step 2: Verify manually**

Run: `.venv\Scripts\python -m vibecheck` with League open, and confirm in `%LOCALAPPDATA%\VibeCheck\vibecheck.log` that a normal (fast-syncing) game still logs `"Captured game ... via match history"` exactly as before — this path is unchanged for the common case. `_create_pending_capture` doesn't exist yet (Task 5), so this task alone will crash on the Arena slow-path; that's expected and fixed by Task 5 landing in the same PR before merge.

- [ ] **Step 3: Commit**

```bash
git add vibecheck/app.py
git commit -m "fix(capture): resolve match history by known game id, not a recent_matches guess (#96)"
```

---

### Task 5: app.py — pending capture + async resolution loop

**Files:**
- Modify: `vibecheck/app.py:682-703` area — add `_create_pending_capture` near `_finish_capture`
- Modify: `vibecheck/app.py:555-572` (`_start_catch_up`) — resolve pending rows in the same sweep
- Modify: `vibecheck/app.py:124-138` (`run`) — start the periodic resolution loop

**Interfaces:**
- Consumes: `GameStore.insert_pending_game`, `GameStore.unresolved_games`, `GameStore.complete_game` (Task 2); `LcuClient.match_details` (existing)
- Produces: `App._create_pending_capture(game_id: int) -> None`; `App._resolve_pending_games() -> None` (caller must hold `self._capture_lock`); `App._start_pending_resolution() -> None`

- [ ] **Step 1: Write the implementation**

Add `_create_pending_capture` in `vibecheck/app.py`, right after `_finish_capture` (after line 703):

```python
    def _create_pending_capture(self, game_id: int) -> None:
        """Two-phase capture for a game whose match history hasn't synced yet
        (issue #96 — Arena regularly takes minutes, not seconds). Ask how it
        went right now, while the moment is fresh, and let
        _resolve_pending_games fill in the real stats later.

        premade_puuids is snapshotted into the stub itself: self._premade_puuids
        is a single shared slot that the *next* lobby's ChampSelect overwrites,
        and that routinely happens before this game resolves.
        """
        game_id_str = str(game_id)
        if self._already_captured(game_id_str):
            return
        played_at = datetime.now().isoformat(timespec="seconds")
        stored_id = self.store.insert_pending_game(game_id_str, played_at, self._premade_puuids)
        self._premade_puuids = set()
        self.store.set_meta(PREMADES_KEY, "")
        if stored_id is None:
            log.info("Pending game %s already stored", game_id_str)
            return
        self._advance_watermark(played_at)
        log.info("Game %s not synced yet; asking for a rating now, stats to follow", game_id_str)
        if not self.paused:
            self._popup_request("show", stored_id, "Stats are still syncing — rate it now")

    def _resolve_pending_games(self) -> None:
        """Complete any pending stub whose match history has caught up.

        Caller must already hold self._capture_lock (see _start_catch_up and
        _start_pending_resolution, the two callers).
        """
        if self._client is None:
            return
        for row in self.store.unresolved_games():
            match = self._client.match_details(int(row["riot_match_id"]))
            if not (isinstance(match, dict) and match.get("gameId")):
                continue
            premades = set(json.loads(row["pending_premades"] or "[]"))
            result = capture.normalize_match(
                match, self._my_puuid, self._champ_names, premades, self._assets
            )
            if self.store.complete_game(row["id"], result["game"], result["teammates"]):
                log.info(
                    "Resolved pending game %s: %s (%s)",
                    row["riot_match_id"],
                    result["game"].get("champion"),
                    result["game"].get("queue_type"),
                )
```

Wire it into the existing catch-up sweep so a pending game can resolve on the very next lobby visit or reconnect, not just the new timer. In `_start_catch_up`'s `worker()` (`vibecheck/app.py:555-572`):

```python
        def worker():
            try:
                # Before the normal sweep: the backfill advances the watermark,
                # so catch-up then correctly sees those games as already ours
                # and doesn't pop a rating prompt for one of them.
                self._backfill_for_onboarding()
                self._catch_up()
                self._resolve_pending_games()
            except Exception:
                log.exception("Catch-up sweep failed")
            finally:
                self._capture_lock.release()
```

Add the periodic safety-net timer, mirroring `_start_update_check`'s exact threading idiom (`vibecheck/app.py:194-219`). Add near it:

```python
    def _start_pending_resolution(self) -> None:
        """Safety net for #96: catch-up only re-checks on the next lobby
        visit or reconnect, and Arena's sync lag (measured 3-10+ minutes)
        routinely outlasts a single lobby visit. This sweeps on its own
        schedule instead, but stays cheap when idle — it only touches the
        LCU when the store actually has an unresolved row.
        """

        def worker():
            while not self._stopping.is_set():
                if self._stopping.wait(PENDING_RESOLUTION_INTERVAL_SECONDS):
                    return
                if not self.store.unresolved_games():
                    continue
                if not self._capture_lock.acquire(blocking=False):
                    continue  # a capture/catch-up is already using the client
                try:
                    self._resolve_pending_games()
                except Exception:
                    log.exception("Pending-game resolution sweep failed")
                finally:
                    self._capture_lock.release()

        threading.Thread(target=worker, name="pending-resolve", daemon=True).start()
```

Add the constant next to `UPDATE_CHECK_INTERVAL_SECONDS` (`vibecheck/app.py:59-61`):

```python
PENDING_RESOLUTION_INTERVAL_SECONDS = 5 * 60  # #96: Arena sync lag measured 3-10+ min live
```

Start the loop in `run()` (`vibecheck/app.py:124-138`), next to `self._start_update_check()`:

```python
        self._start_usage_ping()
        self._start_update_check()
        self._start_pending_resolution()
        self._relabel_queues()
```

- [ ] **Step 2: Verify manually (end-to-end, matches this session's live repro)**

1. Run `.venv\Scripts\python -m vibecheck` and `tools\lcu_monitor.py` side by side, as done live in this debugging session.
2. Play an Arena game to elimination.
3. Confirm in `vibecheck.log`: `end-of-game stats` and the 30s `match_history` retry both fail exactly as before, but instead of the old warning, `"Game %s not synced yet; asking for a rating now, stats to follow"` appears, and the rating popup shows immediately.
4. Rate it.
5. Confirm the game does **not** yet appear on the dashboard (`http://127.0.0.1:8577`).
6. Wait for `tools/lcu_monitor.log`'s `recent_top` to show the new id (3-10+ min, per this session's measurements), then either return to Lobby or wait up to 5 minutes for the new timer.
7. Confirm in `vibecheck.log`: `"Resolved pending game ...: <champion> (Arena)"`.
8. Confirm the game now appears on the dashboard with the rating given in step 4 intact.

- [ ] **Step 3: Commit**

```bash
git add vibecheck/app.py
git commit -m "feat(capture): two-phase pending capture + async resolution for Arena (#96)"
```

---

### Task 6: Visibility for pending games that never resolve

**Why this task exists (risk mitigation):** the biggest product risk in this plan isn't the happy path — it's a pending game that *never* resolves (Riot genuinely drops the match record, a rare LCU quirk, etc.). Without this task, that game's rating silently vanishes: it's rated, then invisible on the dashboard forever, with no signal to the user or the maintainer that anything is stuck. This task doesn't try to fix that (out of scope — Riot's data may really never show up), but it makes the failure observable instead of silent, which is the minimum bar before shipping a fire-and-forget background resolver.

**Files:**
- Modify: `vibecheck/telemetry.py:68-88` (`_payload`)
- Modify: `vibecheck/app.py` — `_resolve_pending_games` (Task 5)

**Interfaces:**
- Consumes: `GameStore.unresolved_games()` (Task 2)

- [ ] **Step 1: Add an aggregate count to telemetry**

In `vibecheck/telemetry.py`, add one field to `_payload` (after line 87, `"schema_migration_failed"`):

```python
        "schema_version": store.schema_version(),
        "schema_migration_failed": store.schema_migration_failed(),
        "pending_capture_count": len(store.unresolved_games()),
```

This is the only aggregate signal that would show if pending-Arena-capture starts piling up across the install base after shipping — the same role `schema_migration_failed` already plays for schema health.

- [ ] **Step 2: Log a warning for individually stale pending rows**

In `_resolve_pending_games` (`vibecheck/app.py`, Task 5), warn once a row has been sitting unresolved long enough that it's no longer "just Arena being slow" — this measured session topped out around 10 minutes, so a day is a generous margin that only fires for genuinely stuck rows:

```python
    def _resolve_pending_games(self) -> None:
        """Complete any pending stub whose match history has caught up.

        Caller must already hold self._capture_lock (see _start_catch_up and
        _start_pending_resolution, the two callers).
        """
        if self._client is None:
            return
        for row in self.store.unresolved_games():
            match = self._client.match_details(int(row["riot_match_id"]))
            if not (isinstance(match, dict) and match.get("gameId")):
                age = datetime.now() - datetime.fromisoformat(row["played_at"])
                if age > timedelta(hours=24):
                    log.warning(
                        "Pending game %s still unresolved after %s — Riot may never "
                        "have synced this one; the rating is kept, stats stay blank",
                        row["riot_match_id"],
                        age,
                    )
                continue
            premades = set(json.loads(row["pending_premades"] or "[]"))
            result = capture.normalize_match(
                match, self._my_puuid, self._champ_names, premades, self._assets
            )
            if self.store.complete_game(row["id"], result["game"], result["teammates"]):
                log.info(
                    "Resolved pending game %s: %s (%s)",
                    row["riot_match_id"],
                    result["game"].get("champion"),
                    result["game"].get("queue_type"),
                )
```

(`row["played_at"]` is the pending-insert-time estimate, not the real game time — fine here, this is only used as a "how long have we been trying" clock, not a display value.)

- [ ] **Step 3: Verify manually**

Run: `.venv\Scripts\python tests\schema_migration_test.py` (covers `test_telemetry_payload_carries_schema_health`, which calls `telemetry._payload` directly — confirms the new field doesn't break the existing payload shape).

- [ ] **Step 4: Commit**

```bash
git add vibecheck/telemetry.py vibecheck/app.py
git commit -m "feat(capture): surface stuck pending-Arena-capture rows instead of silent limbo (#96)"
```

---

### Task 7: Docs — PRD and CLAUDE.md

**Files:**
- Modify: `PRD.md` (F6 row, line 67)
- Modify: `CLAUDE.md` (Commands table, `tests\schema_migration_test.py` line and a new `tests\pending_capture_test.py` line)

**Interfaces:** None (documentation only).

- [ ] **Step 1: Update PRD.md**

In the F6 row (`PRD.md:67`), append a sentence covering the new pending-resolution behavior:

```
| F6 | Survive crashes and restarts (game crash, client restart, tool not running): on connect and on returning to lobby, sweep LCU match history for finished games newer than a stored watermark and not yet in the DB; import them and prompt for the newest (older ones go to pending). First launch looks back 3h max — no deep backfill. A game whose match history hasn't synced yet by the time it ends (Arena regularly takes minutes, not seconds) is rated immediately from a pending stub and completed with real stats once the client's history catches up — see #96. *(Implemented early — pulled forward from Phase 3 after a real game crash during testing.)* | Must |
```

- [ ] **Step 2: Update CLAUDE.md**

In the Commands section's test list, add the new test file next to the existing ones (matches the existing one-line-per-test-file style):

```
.venv\Scripts\python tests\pending_capture_test.py    # pending Arena capture: stub -> resolved, rating survives (#96)
```

- [ ] **Step 3: Commit**

```bash
git add PRD.md CLAUDE.md
git commit -m "docs: describe two-phase pending Arena capture (#96)"
```

---

## Self-Review

**Spec coverage:**
- Root-cause fix (known id instead of `recent_matches()` guessing) — Task 4. ✓
- Two-phase pending/rate-now, resolve-later — Tasks 2, 5. ✓
- Resolution doesn't depend solely on the player returning to lobby soon — Task 5 (catch-up wiring + new timer). ✓
- Dashboard only shows the game once complete — Task 2 (`resolved = 1` filter). ✓
- Rating given at pending time survives resolution — Task 2 test (`test_complete_game_fills_stats_and_keeps_the_rating`). ✓
- Known session-numbering trade-off — documented up top, not silently dropped. ✓
- Biggest product risk (a pending game that never resolves silently loses its rating from view forever) — Task 6, made observable via telemetry + a stale-row log warning rather than fixed outright (Riot may genuinely never sync it — no code change can guarantee resolution, only visibility). ✓
- Docs updated in the same change as the behavior (CLAUDE.md convention) — Task 7. ✓

**Placeholder scan:** No TBD/"add error handling"/"similar to Task N" — every step has real code.

**Type consistency:** `insert_pending_game(riot_match_id: str, played_at: str, premade_puuids: set) -> int | None` (Task 2) matches its call site in `_create_pending_capture` (Task 5). `complete_game(game_id: int, game: dict, teammates: list) -> bool` matches both its test (Task 2) and `_resolve_pending_games` (Task 5). `gameflow_session() -> dict | None` (Task 3) matches its only caller, `_known_game_id` (Task 4).

---

Plan complete and saved to `docs/superpowers/plans/2026-08-16-arena-pending-capture.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
