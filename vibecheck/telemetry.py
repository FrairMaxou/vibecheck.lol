"""Anonymous usage ping — how many installs are out there, and on what version.

Squad sync (sync.py) already tells us about people who *rate* games, but says
nothing about installs that never rate, and nothing at all about which version
someone is running. That last one is what matters the day a release breaks.

What is sent, once a day at most:
    a random install id, the app version, the OS build, and a handful of counts.

What is NEVER sent:
    PUUIDs, summoner names, match ids, tags, notes. The install id is a fresh
    uuid4 with no link to any League account — that is the line between
    telemetry and tracking, and it is not negotiable.

Consent: on by default, documented in the README's Privacy section, with a switch
in the profile menu. When it is off this module makes no network calls at all —
see ping(). That disclosure is what keeps on-by-default honest, and the source
being public means it has to be accurate.

Unlike squad sync there is no signed-in session here: the ping goes out as the
anonymous PostgREST role using only the publishable key. That is deliberate —
it means an install that never rates a game (and so never gets an identity)
still gets counted, which is the entire blind spot this exists to close.
"""

import logging
import platform
import uuid
from datetime import date

import requests

from .config import APP_VERSION
from .store import GameStore
from .sync import load_config

log = logging.getLogger(__name__)

TABLE = "telemetry_pings"
TIMEOUT = 10

INSTALL_ID_KEY = "telemetry_install_id"
ENABLED_KEY = "telemetry_enabled"
LAST_PING_KEY = "telemetry_last_ping"
FIRST_SEEN_KEY = "telemetry_first_seen"


def is_enabled(store: GameStore) -> bool:
    """On unless the user turned it off (the documented default)."""
    return (store.get_meta(ENABLED_KEY) or "1") == "1"


def set_enabled(store: GameStore, value: bool) -> None:
    store.set_meta(ENABLED_KEY, "1" if value else "0")
    log.info("Anonymous usage stats %s", "enabled" if value else "disabled")


def install_id(store: GameStore) -> str:
    """A random id for this install. Never derived from anything identifying."""
    existing = store.get_meta(INSTALL_ID_KEY)
    if existing:
        return existing
    new = str(uuid.uuid4())
    store.set_meta(INSTALL_ID_KEY, new)
    return new


def _payload(store: GameStore) -> dict:
    games = store.games_with_details()
    scores = [g["fun_score"] for g in games if g.get("fun_score") and not g.get("skipped")]
    today = date.today().isoformat()
    first_seen = store.get_meta(FIRST_SEEN_KEY)
    if not first_seen:
        first_seen = today
        store.set_meta(FIRST_SEEN_KEY, first_seen)
    return {
        "install_id": install_id(store),
        "day": today,
        "app_version": APP_VERSION,
        "os": f"{platform.system()} {platform.release()}",
        "first_seen": first_seen,
        "games_captured": len(games),
        "games_rated": len(scores),
        "avg_vibe": round(sum(scores) / len(scores), 2) if scores else None,
        "squad_enabled": bool(load_config()),
    }


def ping(store: GameStore) -> bool:
    """Send at most one ping per day. Returns True if one was sent.

    Never raises and never blocks anything important: telemetry failing is not
    a reason for the app to misbehave, so every path here swallows its errors.
    """
    if not is_enabled(store):
        return False  # opted out: nothing is collected and nothing is sent

    today = date.today().isoformat()
    if store.get_meta(LAST_PING_KEY) == today:
        return False  # already counted today

    cfg = load_config()
    if not cfg:
        return False  # no backend configured (dev, or a self-hosted build)

    try:
        resp = requests.post(
            f"{cfg['url'].rstrip('/')}/rest/v1/{TABLE}",
            headers={
                "apikey": cfg["anon_key"],
                "Authorization": f"Bearer {cfg['anon_key']}",
                "Content-Type": "application/json",
                # return=minimal is load-bearing, not a micro-optimisation:
                # `anon` holds INSERT on this table and nothing else
                # (supabase/harden-grants.sql), so asking PostgREST to return
                # the inserted row would need a SELECT it doesn't have and every
                # ping would start failing with a permission error.
                "Prefer": "return=minimal",
            },
            json=_payload(store),
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        log.debug("Usage ping skipped (%s)", exc.__class__.__name__)
        return False

    # 409 = this install already has a row for today (another instance, or a
    # clock change). That's success as far as we're concerned.
    if resp.status_code < 400 or resp.status_code == 409:
        store.set_meta(LAST_PING_KEY, today)
        log.debug("Usage ping sent (%s)", resp.status_code)
        return True

    log.debug("Usage ping rejected (%s)", resp.status_code)
    return False
