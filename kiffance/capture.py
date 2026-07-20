"""Normalize the LCU end-of-game payload into a game record.

Payload shapes drift across patches, so parsing is defensive: every field is
best-effort with fallbacks, the raw payload is always preserved (PRD F4), and
normalize() never raises — worst case it returns a minimal record.
"""

import logging
from datetime import datetime, timedelta

from .config import QUEUE_NAMES, QUEUE_TYPE_TO_ID

log = logging.getLogger(__name__)


def _stat(stats: dict, *keys, default=0):
    for key in keys:
        if key in stats:
            return stats[key]
    return default


def _duration_seconds(eol: dict) -> int:
    raw = eol.get("gameLength") or eol.get("gameLengthSeconds") or 0
    # Some patches report milliseconds; no real game lasts > 3h.
    return int(raw / 1000) if raw > 10800 else int(raw)


def resolve_queue_id(eol: dict) -> int | None:
    queue_id = eol.get("queueId")
    if isinstance(queue_id, int) and queue_id > 0:
        return queue_id
    return QUEUE_TYPE_TO_ID.get(str(eol.get("queueType", "")).upper())


def normalize(eol: dict, my_puuid: str, champ_names: dict, premade_puuids: set) -> dict:
    """Returns {"game": {...}, "teammates": [...]} ready for GameStore.insert_game."""
    duration = _duration_seconds(eol)
    played_at = (datetime.now() - timedelta(seconds=duration)).isoformat(timespec="seconds")
    queue_id = resolve_queue_id(eol)

    game = {
        "riot_match_id": str(eol.get("gameId", "")) or None,
        "played_at": played_at,
        "queue_id": queue_id,
        "queue_type": QUEUE_NAMES.get(queue_id) or str(eol.get("queueType", "")),
        "duration_seconds": duration,
        "raw_payload": eol,
        "champion": None,
        "role": None,
        "win": None,
        "kills": None,
        "deaths": None,
        "assists": None,
        "cs": None,
    }
    teammates = []

    try:
        me, my_team = _find_me(eol, my_puuid)
        if my_team is not None:
            if "isWinningTeam" in my_team:
                game["win"] = int(bool(my_team.get("isWinningTeam")))
            for player in my_team.get("players", []):
                puuid = player.get("puuid", "")
                if puuid == my_puuid:
                    continue
                teammates.append(
                    {
                        "summoner_name": player.get("summonerName")
                        or player.get("gameName")
                        or player.get("riotIdGameName", ""),
                        "riot_puuid": puuid,
                        "was_premade": puuid in premade_puuids,
                    }
                )
        if me is not None:
            stats = me.get("stats") or {}
            game.update(
                {
                    "champion": me.get("championName") or champ_names.get(me.get("championId"), ""),
                    "role": me.get("selectedPosition") or me.get("position") or "",
                    "kills": _stat(stats, "CHAMPIONS_KILLED", "kills", "championsKilled"),
                    "deaths": _stat(stats, "NUM_DEATHS", "deaths", "numDeaths"),
                    "assists": _stat(stats, "ASSISTS", "assists"),
                    "cs": (
                        _stat(stats, "MINIONS_KILLED", "minionsKilled")
                        + _stat(stats, "NEUTRAL_MINIONS_KILLED", "neutralMinionsKilled")
                    ),
                }
            )
    except Exception as exc:
        log.warning("Partial end-of-game parse (raw payload kept): %s", exc)

    return {"game": game, "teammates": teammates}


def _find_me(eol: dict, my_puuid: str):
    """Locate the local player and their team in the payload."""
    for team in eol.get("teams", []):
        for player in team.get("players", []):
            if player.get("puuid") == my_puuid:
                return player, team
    # Fallback: some payload versions carry a localPlayer object.
    local = eol.get("localPlayer")
    if local:
        team_id = local.get("teamId")
        for team in eol.get("teams", []):
            if team.get("teamId") == team_id:
                return local, team
        return local, None
    return None, None
