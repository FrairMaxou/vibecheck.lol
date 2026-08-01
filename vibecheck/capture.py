"""Normalize the LCU end-of-game payload into a game record.

Payload shapes drift across patches, so parsing is defensive: every field is
best-effort with fallbacks, the raw payload is always preserved (PRD F4), and
normalize() never raises — worst case it returns a minimal record.
"""

import logging
from datetime import datetime, timedelta

from .config import (
    CLASSIC_GAME_MODES,
    CLASSIC_QUEUE_IDS,
    GAME_MODE_NAMES,
    QUEUE_NAMES,
    QUEUE_TYPE_TO_ID,
)

log = logging.getLogger(__name__)


def _stat(stats: dict, *keys, default=0):
    for key in keys:
        if key in stats:
            return stats[key]
    return default


def _resolve(ids, mapping: dict, prefix: str) -> list:
    """Map ids to display names, skipping empty slots (0/None).

    Unknown ids degrade to "Augment 1081" rather than being dropped, so the
    data stays analysable even before the client's asset maps are available.
    """
    out = []
    for raw in ids:
        if not raw:
            continue
        out.append((mapping or {}).get(raw) or f"{prefix} {raw}")
    return out


def _extract_extras(stats: dict, enemy_ids: list, champ_names: dict, assets: dict | None) -> dict:
    """Enemy comp, augments, build, and headline personal stats (PRD §13)."""
    assets = assets or {}
    augment_ids = [
        stats.get(f"playerAugment{n}") or stats.get(f"PLAYER_AUGMENT_{n}") for n in range(1, 7)
    ]
    item_ids = [stats.get(f"item{n}", stats.get(f"ITEM{n}")) for n in range(7)]
    return {
        "enemy_champions": _resolve(enemy_ids, champ_names, "Champion"),
        "augments": _resolve(augment_ids, assets.get("augments"), "Augment"),
        "items": _resolve(item_ids, assets.get("items"), "Item"),
        "damage_to_champs": _stat(
            stats, "totalDamageDealtToChampions", "TOTAL_DAMAGE_DEALT_TO_CHAMPIONS"
        ),
        "gold": _stat(stats, "goldEarned", "GOLD_EARNED"),
    }


def _is_remake(stats: dict) -> bool:
    """Detect a remake/early-surrender from a player's stats (F5).

    Handles both payload shapes: match-history `gameEndedInEarlySurrender`
    and end-of-game `GAME_ENDED_IN_EARLY_SURRENDER`.
    """
    for key, value in stats.items():
        if value and key.lower().replace("_", "") == "gameendedinearlysurrender":
            return True
    return False


def _duration_seconds(eol: dict) -> int:
    raw = eol.get("gameLength") or eol.get("gameLengthSeconds") or 0
    # Some patches report milliseconds; no real game lasts > 3h.
    return int(raw / 1000) if raw > 10800 else int(raw)


def resolve_queue_id(eol: dict) -> int | None:
    queue_id = eol.get("queueId")
    if isinstance(queue_id, int) and queue_id > 0:
        return queue_id
    return QUEUE_TYPE_TO_ID.get(str(eol.get("queueType", "")).upper())


def queue_label(queue_id: int | None, payload: dict) -> str:
    """Friendly queue name; never blank.

    Resolution order, most specific first:
      1. a known queue id
      2. a known gameMode — so a new queue id in a familiar mode still reads as
         "League Classic" rather than "JADE" (Riot ships new ids routinely;
         League Classic alone arrived with four)
      3. the payload's own queue/mode strings, raw
      4. the id itself
    A brand-new mode is therefore always identifiable, never empty.
    """
    known = QUEUE_NAMES.get(queue_id)
    if known:
        return known
    by_mode = GAME_MODE_NAMES.get(str(payload.get("gameMode", "")).upper())
    if by_mode:
        return by_mode
    for field in ("queueType", "gameMode"):
        value = payload.get(field)
        if value:
            return str(value)
    return f"Queue {queue_id}" if queue_id else "Unknown queue"


# The stored labels for Classic queues, derived from the tables above so the
# two can't drift apart.
_CLASSIC_LABELS = {QUEUE_NAMES[q] for q in CLASSIC_QUEUE_IDS if q in QUEUE_NAMES}


def is_classic(queue_id: int | None, queue_type: str | None = None, game_mode: str = "") -> bool:
    """Whether a game was played in League Classic (the Season 3 throwback).

    Three signals, most reliable first: the queue id, the payload's gameMode,
    then the stored label. The label fallback matters because it's all a stored
    row carries — and the gameMode check means a Classic queue id we haven't
    catalogued yet is still recognised, which is the same reason queue_label
    falls back to GAME_MODE_NAMES.
    """
    if queue_id in CLASSIC_QUEUE_IDS:
        return True
    if str(game_mode or "").upper() in CLASSIC_GAME_MODES:
        return True
    return str(queue_type or "") in _CLASSIC_LABELS


def normalize(
    eol: dict, my_puuid: str, champ_names: dict, premade_puuids: set, assets: dict | None = None
) -> dict:
    """Returns {"game": {...}, "teammates": [...]} ready for GameStore.insert_game."""
    duration = _duration_seconds(eol)
    played_at = (datetime.now() - timedelta(seconds=duration)).isoformat(timespec="seconds")
    queue_id = resolve_queue_id(eol)

    game = {
        "riot_match_id": str(eol.get("gameId", "")) or None,
        "played_at": played_at,
        "queue_id": queue_id,
        "queue_type": queue_label(queue_id, eol),
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
                    "is_remake": int(_is_remake(stats)),
                }
            )
            # Win normally comes from the team's isWinningTeam above. Some
            # payload shapes only carry it per-player, so fall back to the
            # player's own stats rather than storing an unknown result.
            if game["win"] is None:
                for key in ("WIN", "win"):
                    if key in stats:
                        game["win"] = int(bool(stats[key]))
                        break
            enemy_ids = [
                p.get("championId")
                for team in eol.get("teams", [])
                if my_team is None or team.get("teamId") != my_team.get("teamId")
                for p in team.get("players", [])
            ]
            game.update(_extract_extras(stats, enemy_ids, champ_names, assets))
    except Exception as exc:
        log.warning("Partial end-of-game parse (raw payload kept): %s", exc)

    return {"game": game, "teammates": teammates}


def normalize_match(
    match: dict, my_puuid: str, champ_names: dict, premade_puuids: set, assets: dict | None = None
) -> dict:
    """Normalize an LCU match-history record (fallback source when the
    end-of-game endpoint never populates, e.g. bot games or fast re-queues).

    Shape: participants[] keyed by participantId + participantIdentities[]
    carrying puuid/name, Match-V4 style.
    """
    duration = int(match.get("gameDuration", 0))
    created_ms = match.get("gameCreation", 0)
    if created_ms:
        played_at = datetime.fromtimestamp(created_ms / 1000).isoformat(timespec="seconds")
    else:
        played_at = (datetime.now() - timedelta(seconds=duration)).isoformat(timespec="seconds")
    queue_id = match.get("queueId") if isinstance(match.get("queueId"), int) else None

    game = {
        "riot_match_id": str(match.get("gameId", "")) or None,
        "played_at": played_at,
        "queue_id": queue_id,
        "queue_type": queue_label(queue_id, match),
        "duration_seconds": duration,
        "raw_payload": match,
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
        identities = {
            ident.get("participantId"): ident.get("player", {})
            for ident in match.get("participantIdentities", [])
        }
        me = None
        for part in match.get("participants", []):
            if identities.get(part.get("participantId"), {}).get("puuid") == my_puuid:
                me = part
                break
        if me is not None:
            stats = me.get("stats") or {}
            game.update(
                {
                    "champion": champ_names.get(me.get("championId"), ""),
                    "role": (me.get("timeline") or {}).get("lane", ""),
                    "win": int(bool(stats.get("win"))) if "win" in stats else None,
                    "kills": stats.get("kills", 0),
                    "deaths": stats.get("deaths", 0),
                    "assists": stats.get("assists", 0),
                    "cs": (
                        stats.get("totalMinionsKilled", 0) + stats.get("neutralMinionsKilled", 0)
                    ),
                    "is_remake": int(_is_remake(stats)),
                }
            )
            enemy_ids = [
                p.get("championId")
                for p in match.get("participants", [])
                if p.get("teamId") != me.get("teamId")
            ]
            game.update(_extract_extras(stats, enemy_ids, champ_names, assets))
            for part in match.get("participants", []):
                if part is me or part.get("teamId") != me.get("teamId"):
                    continue
                player = identities.get(part.get("participantId"), {})
                puuid = player.get("puuid", "")
                teammates.append(
                    {
                        "summoner_name": player.get("gameName") or player.get("summonerName", ""),
                        "riot_puuid": puuid,
                        "was_premade": bool(puuid) and puuid in premade_puuids,
                    }
                )
    except Exception as exc:
        log.warning("Partial match-history parse (raw payload kept): %s", exc)

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
