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
            "stats": {
                "win": False,
                "kills": 4,
                "deaths": 6,
                "assists": 5,
                "totalMinionsKilled": 20,
            },
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

        result = capture.normalize_match(
            FAKE_ARENA_MATCH, MY_PUUID, {79: "Gragas", 34: "Anivia"}, {"friend-1"}
        )
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
