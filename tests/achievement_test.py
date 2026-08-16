"""Verify ARAM God progress: the roster rule, the store, and the API (PRD §16).

The League client half is checked by hand against a live client; everything
here runs on synthetic data so CI can run it.

Two properties are worth this file. **The denominator**: the client's champion
list carries League Classic's alternate versions under the same display names,
and counting them turns 45/173 into 45/233 — a bar that can never fill. **The
difference between empty and unknown**: a failed read must never overwrite
stored progress, because ARAM God is a lifetime figure VibeCheck sees only a
sliver of and cannot rebuild from its own games.

Run: .venv\\Scripts\\python tests\\achievement_test.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from vibecheck import lcu  # noqa: E402
from vibecheck.config import (  # noqa: E402
    ARAM_GOD_KEY,
    ARENA_GOD_KEY,
    ARENA_GOD_MASTER_THRESHOLD,
    ASSETS_CHAMPS_KEY,
)
from vibecheck.dashboard import create_app  # noqa: E402
from vibecheck.store import GameStore  # noqa: E402

# Two modern champions, plus the League Classic variant of one of them. The
# variant reuses the display name and lives in the 60000s, exactly as the
# client ships it.
NAMES = {1: "Annie", 2: "Olaf", 3: "Galio", 60001: "Annie", 60002: "Olaf"}
ROSTER_SIZE = 3


def store_in(root: Path, name: str = "t.sqlite3") -> GameStore:
    return GameStore(root / name)


def api_for(store: GameStore) -> TestClient:
    # base_url matters: TrustedHostMiddleware rejects TestClient's default
    # `testserver` Host, which would turn every assertion into a 400.
    return TestClient(create_app(store), base_url="http://127.0.0.1")


def test_classic_variants_do_not_inflate_the_roster(root):
    roster = lcu.canonical_roster(NAMES)
    assert len(roster) == ROSTER_SIZE, roster
    assert set(roster.values()) == {"Annie", "Olaf", "Galio"}, roster
    # The canonical id is the lowest one, so the modern champion wins.
    assert roster[1] == "Annie" and 60001 not in roster, roster


def test_roster_survives_json_string_keys(root):
    """meta round-trips through JSON, which turns int keys into strings."""
    round_tripped = json.loads(json.dumps(NAMES))
    assert all(isinstance(k, str) for k in round_tripped)
    assert lcu.canonical_roster(round_tripped) == lcu.canonical_roster(NAMES)


def test_junk_roster_does_not_raise(root):
    assert lcu.canonical_roster({}) == {}
    assert lcu.canonical_roster({"nope": "Annie", "-1": "None", "3": ""}) == {}


def test_store_round_trip_and_change_detection(root):
    store = store_in(root)
    assert store.achievement_progress(ARAM_GOD_KEY)["synced_at"] is None

    assert store.set_achievement_champions(ARAM_GOD_KEY, [3, 1], source="client") is True
    progress = store.achievement_progress(ARAM_GOD_KEY)
    assert progress["champion_ids"] == [1, 3], progress
    assert progress["source"] == "client"
    assert progress["synced_at"]

    # Re-reading the same set on every client connect must not look like news:
    # an unconditional revision bump makes an open dashboard reload itself
    # every time the League client restarts.
    rev = store.data_revision()
    assert store.set_achievement_champions(ARAM_GOD_KEY, [1, 3], source="client") is False
    assert store.data_revision() == rev
    assert store.set_achievement_champions(ARAM_GOD_KEY, [1, 2, 3], source="client") is True
    assert store.data_revision() > rev
    store.close()


def test_completing_fewer_champions_removes_rows(root):
    """The client is the source of truth, including when it says less."""
    store = store_in(root)
    store.set_achievement_champions(ARAM_GOD_KEY, [1, 2, 3])
    store.set_achievement_champions(ARAM_GOD_KEY, [2])
    assert store.achievement_progress(ARAM_GOD_KEY)["champion_ids"] == [2]
    store.close()


def test_summary_row_never_becomes_a_champion(root):
    """champion_id 0 is the bookkeeping row and must stay out of the set."""
    store = store_in(root)
    store.set_achievement_champions(ARAM_GOD_KEY, [1])
    assert 0 not in store.achievement_progress(ARAM_GOD_KEY)["champion_ids"]
    store.close()


def test_api_reports_progress_against_the_canonical_roster(root):
    store = store_in(root)
    store.set_meta(ASSETS_CHAMPS_KEY, json.dumps(NAMES))
    store.set_achievement_champions(ARAM_GOD_KEY, [1], source="client")

    body = api_for(store).get("/api/aram-god").json()
    assert body["tracked"] is True, body
    assert body["total"] == ROSTER_SIZE, body
    assert body["completed"] == 1, body
    assert len(body["champions"]) == ROSTER_SIZE, body
    assert [c["name"] for c in body["champions"]] == ["Annie", "Galio", "Olaf"], body
    assert body["champions"][0]["done"] is True, body
    assert sum(c["done"] for c in body["champions"]) == 1, body
    store.close()


def test_api_score_never_exceeds_the_grid(root):
    """A completed champion the cached roster doesn't know must not be counted.

    Otherwise a champion released since the last time we saw the client scores
    4/3 above a grid with 3 cells lit, and the panel just looks broken.
    """
    store = store_in(root)
    store.set_meta(ASSETS_CHAMPS_KEY, json.dumps(NAMES))
    store.set_achievement_champions(ARAM_GOD_KEY, [1, 2, 3, 999], source="client")

    body = api_for(store).get("/api/aram-god").json()
    assert body["total"] == ROSTER_SIZE, body
    assert body["completed"] == ROSTER_SIZE, body
    assert body["completed"] == sum(c["done"] for c in body["champions"]), body
    # The store still holds it — the client is the source of truth, and the
    # roster catching up must not need a re-sync to restore the count.
    assert 999 in store.achievement_progress(ARAM_GOD_KEY)["champion_ids"]
    store.close()


def test_api_is_untracked_before_the_first_sync(root):
    """A fresh install must not claim a confident 0/173 it hasn't earned."""
    store = store_in(root)
    store.set_meta(ASSETS_CHAMPS_KEY, json.dumps(NAMES))
    body = api_for(store).get("/api/aram-god").json()
    assert body["tracked"] is False, body
    assert body["completed"] == 0 and body["total"] == ROSTER_SIZE, body
    store.close()


def test_api_survives_a_missing_or_corrupt_roster(root):
    for value in (None, "not json", "[]"):
        store = store_in(root, f"r{abs(hash(value))}.sqlite3")
        if value is not None:
            store.set_meta(ASSETS_CHAMPS_KEY, value)
        body = api_for(store).get("/api/aram-god").json()
        assert body["total"] == 0 and body["champions"] == [], (value, body)
        assert body["tracked"] is False, (value, body)
        store.close()


def test_arena_god_total_is_the_master_threshold_not_the_roster(root):
    """Unlike ARAM God, Arena God's denominator is Riot's own 60-champion
    Master threshold (issue #103) — this challenge was never designed as a
    full-roster grind, so the roster size (3, in this test's synthetic
    NAMES) would understate the real finish line, not just be inconvenient.
    """
    store = store_in(root)
    store.set_meta(ASSETS_CHAMPS_KEY, json.dumps(NAMES))
    store.set_achievement_champions(ARENA_GOD_KEY, [1, 2], source="client")

    body = api_for(store).get("/api/arena-god").json()
    assert body["tracked"] is True, body
    assert body["total"] == ARENA_GOD_MASTER_THRESHOLD, body
    assert body["completed"] == 2, body
    # The grid still shows the whole roster, same as ARAM God's — a player
    # needs to see *which* champions still need an Arena win, not just a
    # bare count against 60.
    assert len(body["champions"]) == ROSTER_SIZE, body
    store.close()


def test_arena_god_tracked_independently_of_aram_god(root):
    """The two achievements share the generic store methods (same `key`
    parameter, different string) — this pins that they don't share state.
    """
    store = store_in(root)
    store.set_meta(ASSETS_CHAMPS_KEY, json.dumps(NAMES))
    store.set_achievement_champions(ARAM_GOD_KEY, [1, 2, 3], source="client")

    body = api_for(store).get("/api/arena-god").json()
    assert body["tracked"] is False, body
    assert body["completed"] == 0, body
    assert api_for(store).get("/api/aram-god").json()["completed"] == 3
    store.close()


TESTS = [
    test_classic_variants_do_not_inflate_the_roster,
    test_roster_survives_json_string_keys,
    test_junk_roster_does_not_raise,
    test_store_round_trip_and_change_detection,
    test_completing_fewer_champions_removes_rows,
    test_summary_row_never_becomes_a_champion,
    test_api_reports_progress_against_the_canonical_roster,
    test_api_score_never_exceeds_the_grid,
    test_api_is_untracked_before_the_first_sync,
    test_api_survives_a_missing_or_corrupt_roster,
    test_arena_god_total_is_the_master_threshold_not_the_roster,
    test_arena_god_tracked_independently_of_aram_god,
]


def main():
    for test in TESTS:
        root = Path(tempfile.mkdtemp(prefix="vibecheck-achievement-"))
        try:
            test(root)
            print(f"  ok  {test.__name__}")
        finally:
            shutil.rmtree(root, ignore_errors=True)
    print("achievement test OK")


if __name__ == "__main__":
    main()
