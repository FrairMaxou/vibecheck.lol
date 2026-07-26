"""Backfill the §13 analysis fields (enemy comp, augments, build, damage/gold).

Re-parses every stored raw payload — no games need replaying, which is exactly
what F4 (keep the raw payload) was for. Safe to re-run.

Name lookups come from the maps the app cached the last time it saw the League
client; if the client is running now, fresh maps are fetched instead. Without
either, ids degrade to "Augment 1081" rather than being lost.

Run: .venv\\Scripts\\python tools\\backfill_analysis.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiffance import capture, lcu
from kiffance.app import (
    ASSETS_AUGMENTS_KEY,
    ASSETS_CHAMPS_KEY,
    ASSETS_ITEMS_KEY,
    MY_PUUID_KEY,
)
from kiffance.store import GameStore


def _int_keys(mapping: dict) -> dict:
    """JSON object keys are strings; payload ids are ints."""
    out = {}
    for key, value in (mapping or {}).items():
        try:
            out[int(key)] = value
        except (TypeError, ValueError):
            continue
    return out


def load_lookups(store: GameStore) -> tuple:
    conn = lcu.discover()
    if conn is not None:
        client = lcu.LcuClient(conn)
        champs = client.champion_names()
        items, augments = client.item_names(), client.augment_names()
        if champs and items:
            print("using live asset maps from the League client")
            return champs, {"items": items, "augments": augments}

    print("League client not running — using the maps cached by the app")
    return (
        _int_keys(json.loads(store.get_meta(ASSETS_CHAMPS_KEY) or "{}")),
        {
            "items": _int_keys(json.loads(store.get_meta(ASSETS_ITEMS_KEY) or "{}")),
            "augments": _int_keys(json.loads(store.get_meta(ASSETS_AUGMENTS_KEY) or "{}")),
        },
    )


def find_my_puuid(payload: dict, game: dict, champs: dict) -> str | None:
    """Fallback identification: the player on my team who isn't a stored
    teammate and whose champion matches the one recorded for this game."""
    known = {t["puuid"] for t in game.get("teammates", []) if t.get("puuid")}
    identities = {
        i.get("participantId"): i.get("player", {})
        for i in payload.get("participantIdentities", [])
    }
    for part in payload.get("participants", []):
        puuid = identities.get(part.get("participantId"), {}).get("puuid")
        if puuid and puuid not in known and champs.get(part.get("championId")) == game["champion"]:
            return puuid
    for team in payload.get("teams", []):
        for player in team.get("players", []):
            puuid = player.get("puuid")
            name = player.get("championName") or champs.get(player.get("championId"))
            if puuid and puuid not in known and name == game["champion"]:
                return puuid
    return None


def main():
    store = GameStore()
    champs, assets = load_lookups(store)
    if not champs:
        print("no champion names available — run once with League open for readable names")

    my_puuid = store.get_meta(MY_PUUID_KEY)
    games = {g["id"]: g for g in store.games_with_details()}
    updated = skipped = 0

    for row in store.games_with_raw():
        game = games.get(row["id"])
        if game is None:
            continue
        try:
            payload = json.loads(row["raw_payload"])
        except (TypeError, ValueError):
            skipped += 1
            continue

        puuid = my_puuid or find_my_puuid(payload, game, champs)
        if not puuid:
            print(f"  game {row['id']}: could not identify you in the payload — skipped")
            skipped += 1
            continue

        parsed = (
            capture.normalize_match(payload, puuid, champs, set(), assets)
            if "participantIdentities" in payload
            else capture.normalize(payload, puuid, champs, set(), assets)
        )
        fields = parsed["game"]
        store.set_analysis_fields(row["id"], fields)
        updated += 1
        print(
            f"  game {row['id']} ({game['champion']}): "
            f"vs {', '.join(fields.get('enemy_champions') or []) or '?'} | "
            f"augments: {', '.join(fields.get('augments') or []) or '—'}"
        )

    print(f"\nbackfilled {updated} game(s)" + (f", skipped {skipped}" if skipped else ""))
    store.close()


if __name__ == "__main__":
    main()
