"""End-to-end smoke test of capture.normalize + GameStore, no League client needed.

Run: .venv\\Scripts\\python tests\\smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiffance import capture
from kiffance.store import GameStore

MY_PUUID = "me-1234"

FAKE_EOL = {
    "gameId": 987654321,
    "gameLength": 1856,
    "queueId": 450,
    "queueType": "ARAM_UNRANKED_5x5",
    "teams": [
        {
            "teamId": 100,
            "isWinningTeam": True,
            "players": [
                {
                    "puuid": MY_PUUID,
                    "summonerName": "Maxime",
                    "championId": 202,
                    "selectedPosition": "",
                    "stats": {
                        "CHAMPIONS_KILLED": 12,
                        "NUM_DEATHS": 3,
                        "ASSISTS": 9,
                        "MINIONS_KILLED": 40,
                        "NEUTRAL_MINIONS_KILLED": 2,
                    },
                },
                {
                    "puuid": "friend-1",
                    "summonerName": "Alex",
                    "championId": 157,
                    "stats": {"CHAMPIONS_KILLED": 2, "NUM_DEATHS": 8, "ASSISTS": 4},
                },
                {"puuid": "rando-1", "summonerName": "Stranger", "championId": 1, "stats": {}},
            ],
        },
        {"teamId": 200, "isWinningTeam": False, "players": []},
    ],
}


def main():
    champ_names = {202: "Jhin", 157: "Yasuo", 1: "Annie"}

    result = capture.normalize(FAKE_EOL, MY_PUUID, champ_names, premade_puuids={"friend-1"})
    game, teammates = result["game"], result["teammates"]

    assert game["champion"] == "Jhin", game
    assert game["win"] == 1
    assert (game["kills"], game["deaths"], game["assists"]) == (12, 3, 9)
    assert game["cs"] == 42
    assert game["duration_seconds"] == 1856
    assert game["queue_id"] == 450 and game["queue_type"] == "ARAM"
    assert game["riot_match_id"] == "987654321"
    assert game["raw_payload"] == FAKE_EOL  # F4: raw payload preserved
    assert capture.resolve_queue_id(FAKE_EOL) == 450

    premade = {t["riot_puuid"]: t["was_premade"] for t in teammates}
    assert premade == {"friend-1": True, "rando-1": False}, teammates

    with tempfile.TemporaryDirectory() as tmp:
        store = GameStore(Path(tmp) / "test.sqlite3")
        game_id = store.insert_game(game, teammates)
        assert game_id is not None
        assert store.insert_game(game, teammates) is None  # dedup on riot_match_id
        assert store.game_count() == 1

        pending = store.pending_games()
        assert len(pending) == 1 and pending[0]["id"] == game_id
        assert pending[0]["session_id"] == 1 and pending[0]["game_index_in_session"] == 1

        store.set_rating(game_id, 5)
        assert store.pending_games() == []

        # A second game 20 minutes later joins the same session.
        game2 = dict(game, riot_match_id="987654322", played_at="2099-01-01T21:00:00")
        game1_end_plus_20m = dict(game, riot_match_id="987654323", played_at="2099-01-01T21:51:00")
        store.insert_game(game2, [])
        gid3 = store.insert_game(game1_end_plus_20m, [])
        row = [g for g in store.pending_games() if g["id"] == gid3][0]
        assert row["game_index_in_session"] == 2, row
        store.close()

    print("smoke test OK")


if __name__ == "__main__":
    main()
