"""Thin adapter around the LCU (local League client API).

The LCU is unofficial and shifts with patches (PRD §6a/§10): every call to it
lives here, behind this module, and failures are logged loudly rather than
swallowed silently.
"""

import base64
import contextlib
import json
import logging
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass

import psutil
import requests
import urllib3
import websocket

log = logging.getLogger(__name__)

# The LCU serves a self-signed Riot cert on 127.0.0.1; verification is
# intentionally disabled for this local-only connection.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GAMEFLOW_EVENT = "OnJsonApiEvent_lol-gameflow_v1_gameflow-phase"

# Every challenge the account knows about, in one payload (~400 entries).
CHALLENGES_PATH = "/lol-challenges/v1/challenges/local-player"


def canonical_roster(champion_names: dict) -> dict:
    """The playable roster — one entry per champion — from an id→name map.

    `champion_names()` deliberately keeps every id the client ships, League
    Classic's alternate versions included: capture needs them to name a Jade
    pick. Anything that asks "how many champions are there" must not, because
    the Classic variants reuse the modern champion's display name and would
    inflate the roster from 173 to 233 — an ARAM God bar that can never fill.

    Canonical means the lowest id for a display name, the same rule ddragon.py
    uses to pick art. Derived from the data rather than an id cutoff or a
    `Jade_` prefix, either of which rots the next time Riot ships a variant set.
    """
    lowest: dict[str, int] = {}
    for champ_id, name in (champion_names or {}).items():
        try:
            champ_id = int(champ_id)  # meta round-trips through JSON, so keys are strings
        except (TypeError, ValueError):
            continue
        if name and champ_id > 0 and champ_id < lowest.get(name, 1 << 30):
            lowest[name] = champ_id
    return {champ_id: name for name, champ_id in lowest.items()}


@dataclass
class LcuConnection:
    port: int
    token: str


def discover() -> LcuConnection | None:
    """Find the running League client via its process command line.

    More robust than the lockfile because it works for any install path.
    """
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.info["name"] != "LeagueClientUx.exe":
                continue
            port = token = None
            for arg in proc.info["cmdline"] or []:
                if arg.startswith("--app-port="):
                    port = int(arg.split("=", 1)[1])
                elif arg.startswith("--remoting-auth-token="):
                    token = arg.split("=", 1)[1]
            if port and token:
                return LcuConnection(port=port, token=token)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            continue
    return None


class LcuClient:
    def __init__(self, conn: LcuConnection):
        self._base = f"https://127.0.0.1:{conn.port}"
        self._session = requests.Session()
        self._session.auth = ("riot", conn.token)
        self._session.verify = False

    def get(self, path: str, timeout: float = 10.0):
        """GET a JSON endpoint; returns None on any failure (logged)."""
        try:
            resp = self._session.get(self._base + path, timeout=timeout)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            log.warning("LCU GET %s failed: %s", path, exc)
            return None

    def current_summoner(self):
        return self.get("/lol-summoner/v1/current-summoner")

    def gameflow_phase(self) -> str | None:
        phase = self.get("/lol-gameflow/v1/gameflow-phase")
        return phase if isinstance(phase, str) else None

    def end_of_game_stats(self):
        return self.get("/lol-end-of-game/v1/eol-game-data")

    def recent_matches(self, count: int = 10) -> list:
        """Most recent games (summary records) from the client's match history."""
        data = self.get(
            f"/lol-match-history/v1/products/lol/current-summoner/matches"
            f"?begIndex=0&endIndex={count}"
        )
        games = (data or {}).get("games", {}).get("games", [])
        return games if isinstance(games, list) else []

    def latest_match_id(self) -> int | None:
        games = self.recent_matches(3)
        if not games:
            return None
        newest = max(games, key=lambda g: g.get("gameCreation", 0))
        return newest.get("gameId")

    def match_details(self, game_id: int):
        """Full match record (all participants) for one game."""
        return self.get(f"/lol-match-history/v1/games/{game_id}")

    def lobby_members(self) -> list:
        lobby = self.get("/lol-lobby/v2/lobby/members")
        return lobby if isinstance(lobby, list) else []

    def friends(self) -> list:
        """The logged-in summoner's League friends list.

        Each entry carries a puuid + gameName. This is what powers zero-config
        squads (§12): your squad is simply the friends who also run VibeCheck and
        list you back (mutual), so no invite codes or accounts are needed.
        """
        data = self.get("/lol-chat/v1/friends")
        return data if isinstance(data, list) else []

    def champion_names(self) -> dict:
        """championId -> name, from the client's static asset data."""
        summary = self.get("/lol-game-data/assets/v1/champion-summary.json")
        if not isinstance(summary, list):
            return {}
        return {c["id"]: c["name"] for c in summary if c.get("id", -1) > 0}

    def challenge(self, challenge_id: int) -> dict | None:
        """One challenge's progress for the logged-in player, or None.

        The endpoint answers with a dict keyed by challenge id **as a string**
        — not the list the rest of these endpoints return — carrying every
        challenge at once, so this indexes rather than scans. A challenge Riot
        has retired simply stops appearing, which lands here as None.
        """
        data = self.get(CHALLENGES_PATH)
        if not isinstance(data, dict):
            return None
        entry = data.get(str(challenge_id))
        return entry if isinstance(entry, dict) else None

    def completed_champion_ids(self, challenge_id: int) -> list[int] | None:
        """Champions already completed for a per-champion challenge.

        **None and [] mean different things.** None is "we could not read it"
        — client closed, challenge retired, payload shape drifted — and the
        caller must keep whatever it stored last. [] is a real answer: the
        player has completed none. Conflating them wipes a lifetime figure we
        cannot rebuild, which is the one unrecoverable mistake available here.
        """
        entry = self.challenge(challenge_id)
        if entry is None:
            return None
        # The flag that says completedIds are champion ids rather than, say,
        # queue ids. 74 challenges declare one, so this is a shared mechanism
        # and worth checking instead of assuming.
        if entry.get("idListType") != "CHAMPION":
            log.warning(
                "Challenge %s is no longer a champion list (idListType=%r) — not syncing",
                challenge_id,
                entry.get("idListType"),
            )
            return None
        ids = entry.get("completedIds")
        if not isinstance(ids, list):
            log.warning("Challenge %s has no completedIds list", challenge_id)
            return None
        return sorted({c for c in ids if isinstance(c, int) and c > 0})

    def item_names(self) -> dict:
        """itemId -> name (for build analysis, §13)."""
        data = self.get("/lol-game-data/assets/v1/items.json")
        if not isinstance(data, list):
            return {}
        return {i["id"]: i["name"] for i in data if isinstance(i.get("id"), int)}

    def augment_names(self) -> dict:
        """augmentId -> name. Covers ARAM Mayhem and Arena augments (§13)."""
        data = self.get("/lol-game-data/assets/v1/cherry-augments.json")
        if not isinstance(data, list):
            return {}
        return {
            a["id"]: (a.get("nameTRA") or a.get("augmentNameId") or "")
            for a in data
            if isinstance(a.get("id"), int)
        }


class GameflowEvents:
    """Event-driven gameflow-phase subscription over the LCU WebSocket.

    Blocks in run() until the socket closes (client exited). No polling:
    the process sleeps until the client pushes a phase change (PRD §6b N1).
    """

    def __init__(self, conn: LcuConnection, on_phase: Callable[[str], None]):
        self._conn = conn
        self._on_phase = on_phase
        self._ws: websocket.WebSocketApp | None = None
        self._stopped = threading.Event()

    def run(self) -> None:
        auth = base64.b64encode(f"riot:{self._conn.token}".encode()).decode()
        self._ws = websocket.WebSocketApp(
            f"wss://127.0.0.1:{self._conn.port}/",
            header=[f"Authorization: Basic {auth}"],
            on_open=self._subscribe,
            on_message=self._handle_message,
        )
        # ping_interval is essential for a long-running tray app: without it a
        # half-open socket (client sleep, network blip) is never detected, so
        # run_forever blocks forever on a dead connection and games played after
        # go uncaptured. With it, a missed pong closes the socket, run_forever
        # returns, and the watcher reconnects.
        self._ws.run_forever(
            sslopt={"cert_reqs": ssl.CERT_NONE},
            ping_interval=30,
            ping_timeout=10,
        )

    def stop(self) -> None:
        self._stopped.set()
        if self._ws:
            with contextlib.suppress(Exception):
                self._ws.close()

    def _subscribe(self, ws) -> None:
        # LCU wamp-style subscribe: opcode 5.
        ws.send(json.dumps([5, GAMEFLOW_EVENT]))
        log.info("Subscribed to gameflow events")

    def _handle_message(self, ws, message: str) -> None:
        if self._stopped.is_set() or not message:
            return  # the LCU sends an empty ack frame right after subscribing
        try:
            parsed = json.loads(message)
            # Events arrive as [8, eventName, {"data": <phase>, ...}]
            if isinstance(parsed, list) and len(parsed) == 3 and parsed[1] == GAMEFLOW_EVENT:
                phase = parsed[2].get("data")
                if isinstance(phase, str):
                    self._on_phase(phase)
        except Exception as exc:
            log.warning("Bad LCU event message: %s", exc)
