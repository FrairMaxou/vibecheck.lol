"""End-to-end smoke test of capture.normalize + GameStore, no League client needed.

Run: .venv\\Scripts\\python tests\\smoke_test.py
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vibecheck import capture, config, whatsnew
from vibecheck.store import GameStore

MY_PUUID = "me-1234"


def check_release_notes():
    """The version being shipped must have a what's-new entry.

    release-please bumps APP_VERSION on its own, so nothing else would notice
    that the card users see after updating was never written. This fails the
    Release PR's CI until someone writes it — which is the point: it's the one
    step of a release that a machine can't do.
    """
    assert whatsnew.notes_for(config.APP_VERSION), (
        f"no what's-new entry for {config.APP_VERSION} — add one to "
        f"vibecheck/whatsnew.py before releasing"
    )


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


FAKE_MATCH_HISTORY = {
    "gameId": 555000111,
    "gameCreation": 1789000000000,
    "gameDuration": 1420,
    "queueId": 870,
    "participants": [
        {
            "participantId": 1,
            "teamId": 100,
            "championId": 202,
            "timeline": {"lane": "BOTTOM"},
            "stats": {
                "win": True,
                "kills": 15,
                "deaths": 2,
                "assists": 7,
                "totalMinionsKilled": 120,
                "neutralMinionsKilled": 8,
            },
        },
        {
            "participantId": 2,
            "teamId": 100,
            "championId": 157,
            "stats": {"win": True, "kills": 3, "deaths": 5, "assists": 2},
        },
        {"participantId": 3, "teamId": 200, "championId": 1, "stats": {"win": False}},
    ],
    "participantIdentities": [
        {"participantId": 1, "player": {"puuid": MY_PUUID, "gameName": "Maxime"}},
        {"participantId": 2, "player": {"puuid": "friend-1", "gameName": "Alex"}},
        {"participantId": 3, "player": {"puuid": "bot-1", "gameName": "Annie Bot"}},
    ],
}


def test_match_history_fallback():
    champ_names = {202: "Jhin", 157: "Yasuo", 1: "Annie"}
    result = capture.normalize_match(
        FAKE_MATCH_HISTORY, MY_PUUID, champ_names, premade_puuids={"friend-1"}
    )
    game, teammates = result["game"], result["teammates"]

    assert game["champion"] == "Jhin", game
    assert game["win"] == 1
    assert (game["kills"], game["deaths"], game["assists"]) == (15, 2, 7)
    assert game["cs"] == 128
    assert game["duration_seconds"] == 1420
    assert game["queue_type"] == "Co-op vs AI (Intro)", game
    assert game["riot_match_id"] == "555000111"
    assert game["raw_payload"] == FAKE_MATCH_HISTORY
    # Only same-team players; the enemy-team bot is excluded.
    assert [t["riot_puuid"] for t in teammates] == ["friend-1"], teammates
    assert teammates[0]["was_premade"] is True


def test_remake_detection():
    """F5: a remake is flagged from the early-surrender stat, both payload shapes."""
    champ_names = {202: "Jhin"}

    # normal game -> not a remake
    normal = capture.normalize_match(FAKE_MATCH_HISTORY, MY_PUUID, champ_names, set())
    assert normal["game"]["is_remake"] == 0

    # match-history shape (camelCase flag)
    remade = json.loads(json.dumps(FAKE_MATCH_HISTORY))
    remade["participants"][0]["stats"]["gameEndedInEarlySurrender"] = True
    out = capture.normalize_match(remade, MY_PUUID, champ_names, set())
    assert out["game"]["is_remake"] == 1, out["game"]

    # end-of-game shape (SCREAMING_SNAKE flag)
    eol = json.loads(json.dumps(FAKE_EOL))
    eol["teams"][0]["players"][0]["stats"]["GAME_ENDED_IN_EARLY_SURRENDER"] = True
    out = capture.normalize(eol, MY_PUUID, champ_names, set())
    assert out["game"]["is_remake"] == 1, out["game"]

    # a remake is stored but never appears as pending (so it's never prompted)
    with tempfile.TemporaryDirectory() as tmp:
        store = GameStore(Path(tmp) / "remake.sqlite3")
        gid = store.insert_game(out["game"], [])
        assert gid is not None
        assert store.pending_games() == [], "remake should not be pending"
        store.close()


def test_queue_label_fallback():
    # known ids -> friendly labels
    assert capture.queue_label(450, {}) == "ARAM"
    assert capture.queue_label(2400, {"gameMode": "KIWI"}) == "ARAM Mayhem"
    # League Classic (patch 26.15): new ids on the new "JADE" mode
    assert capture.queue_label(4310, {"gameMode": "JADE"}) == "League Classic"
    assert capture.queue_label(2450, {"gameMode": "KIWI_JADE"}) == "ARAM Mayhem Classic-ish"
    # unknown id but a known gameMode -> the mode's friendly name, so a queue id
    # Riot adds later still reads properly instead of showing "JADE"
    assert capture.queue_label(9999, {"gameMode": "JADE"}) == "League Classic"
    assert capture.queue_label(9999, {"gameMode": "NEXUSBLITZ"}) == "Nexus Blitz"
    # unknown id AND unknown mode -> raw string (the blank-queue bug this guards)
    assert capture.queue_label(9999, {"gameMode": "SOME_FUTURE_MODE"}) == "SOME_FUTURE_MODE"
    # unknown id, no strings -> never blank
    assert capture.queue_label(9999, {}) == "Queue 9999"
    assert capture.queue_label(None, {}) == "Unknown queue"


def test_win_fallback():
    """Win must survive a payload that only reports it per-player (F3b spirit:
    new modes must not silently record an unknown result)."""
    eol = {
        "gameId": 1,
        "queueId": 4310,
        "gameMode": "JADE",
        "gameLength": 1800,
        "teams": [
            {
                "teamId": 100,
                "isPlayerTeam": True,
                "players": [{"puuid": "ME", "championId": 84, "stats": {"WIN": 1}}],
            },
            {"teamId": 200, "players": [{"puuid": "E", "championId": 86, "stats": {"WIN": 0}}]},
        ],
    }
    game = capture.normalize(eol, "ME", {84: "Akali", 86: "Garen"}, set(), {})["game"]
    assert game["win"] == 1, "win should fall back to the player's own stats"
    assert game["queue_type"] == "League Classic"


def main():
    test_match_history_fallback()
    test_remake_detection()
    test_queue_label_fallback()
    test_win_fallback()
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

        # meta store (used by the F6 catch-up watermark)
        assert store.get_meta("capture_watermark") is None
        store.set_meta("capture_watermark", "2099-01-01T20:00:00")
        store.set_meta("capture_watermark", "2099-01-01T21:00:00")
        assert store.get_meta("capture_watermark") == "2099-01-01T21:00:00"
        assert store.has_game("987654321") and not store.has_game("nope")

        # tags & notes (F9)
        assert "Hard carried" in store.list_tags()  # defaults seeded
        store.set_game_tags(game_id, ["Hard carried", "Custom vibe"])  # unknown label auto-created
        assert "Custom vibe" in store.list_tags()
        detail = next(g for g in store.games_with_details() if g["id"] == game_id)
        assert sorted(detail["tags"]) == ["Custom vibe", "Hard carried"], detail["tags"]
        store.set_game_tags(game_id, ["Hard carried"])  # replace, not append
        detail = next(g for g in store.games_with_details() if g["id"] == game_id)
        assert detail["tags"] == ["Hard carried"], detail["tags"]

        # a note on an UNRATED game must not make it drop off the pending list
        note_gid = store.insert_game(
            dict(game, riot_match_id="987654999", played_at="2099-01-02T10:00:00"), []
        )
        store.set_note(note_gid, "int diff from minute 1")
        assert any(g["id"] == note_gid for g in store.pending_games()), "note dropped pending game"
        detail = next(g for g in store.games_with_details() if g["id"] == note_gid)
        assert detail["note"] == "int diff from minute 1"
        store.close()

    check_release_notes()
    print("smoke test OK")


if __name__ == "__main__":
    main()
