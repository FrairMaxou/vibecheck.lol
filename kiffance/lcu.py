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

    def champion_names(self) -> dict:
        """championId -> name, from the client's static asset data."""
        summary = self.get("/lol-game-data/assets/v1/champion-summary.json")
        if not isinstance(summary, list):
            return {}
        return {c["id"]: c["name"] for c in summary if c.get("id", -1) > 0}


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
        self._ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

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
