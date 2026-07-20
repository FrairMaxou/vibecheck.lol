"""Orchestration: threads, gameflow handling, and the Tk main loop.

Threading model:
- main thread: hidden Tk root + RatingPopup (Tk requires the main thread);
  drains a queue of UI requests posted by other threads.
- watcher thread: finds the League client, then blocks on the LCU WebSocket
  (event-driven, no polling while connected) and reconnects if the client exits.
- tray thread: pystray icon.
"""

import logging
import queue
import threading
import time
import tkinter as tk

from . import capture, lcu
from .config import APP_NAME, CLIENT_POLL_SECONDS, DATA_DIR, LOG_PATH
from .popup import RatingPopup
from .store import GameStore
from .tray import build_tray

log = logging.getLogger(__name__)

# Gameflow phases that mean a game is (about to be) over / live.
END_PHASES = {"PreEndOfGame", "EndOfGame"}
LIVE_PHASES = {"InProgress"}
LOBBY_PHASES = {"ChampSelect", "InProgress"}


class App:
    def __init__(self):
        self.store = GameStore()
        self.paused = False
        self._stopping = threading.Event()
        self._ui_requests: queue.Queue = queue.Queue()

        self._client: lcu.LcuClient | None = None
        self._events: lcu.GameflowEvents | None = None
        self._my_puuid: str | None = None
        self._champ_names: dict = {}
        self._premade_puuids: set = set()
        self._processed_game_ids: set = set()
        self._capture_lock = threading.Lock()

        self._root = tk.Tk()
        self._root.withdraw()
        self._popup = RatingPopup(self._root, self._on_rate)
        self._tray = build_tray(
            is_paused=lambda: self.paused,
            toggle_paused=self._toggle_paused,
            on_quit=self.stop,
        )

    # ---------------- lifecycle ----------------

    def run(self) -> None:
        log.info("%s starting (%d games in store)", APP_NAME, self.store.game_count())
        threading.Thread(target=self._watcher_loop, name="lcu-watcher", daemon=True).start()
        threading.Thread(target=self._tray.run, name="tray", daemon=True).start()
        self._root.after(100, self._drain_ui_requests)
        self._root.mainloop()

    def stop(self) -> None:
        self._stopping.set()
        if self._events:
            self._events.stop()
        self._tray.stop()
        self.store.close()
        # Quit Tk from its own thread.
        self._root.after(0, self._root.quit)

    def _toggle_paused(self) -> None:
        self.paused = not self.paused
        log.info("Prompts %s", "paused" if self.paused else "resumed")

    # ---------------- watcher thread ----------------

    def _watcher_loop(self) -> None:
        while not self._stopping.is_set():
            conn = lcu.discover()
            if conn is None:
                self._stopping.wait(CLIENT_POLL_SECONDS)
                continue

            self._client = lcu.LcuClient(conn)
            summoner = self._client.current_summoner()
            if not summoner or "puuid" not in summoner:
                # Client process is up but the API isn't ready yet.
                self._stopping.wait(CLIENT_POLL_SECONDS)
                continue
            self._my_puuid = summoner["puuid"]
            self._champ_names = self._client.champion_names()
            log.info(
                "Connected to League client (summoner: %s)",
                summoner.get("gameName") or summoner.get("displayName", "?"),
            )

            # Catch a game that ended while we weren't listening.
            phase = self._client.gameflow_phase()
            if phase in END_PHASES:
                self._handle_end_of_game()

            self._events = lcu.GameflowEvents(conn, self._on_phase)
            self._events.run()  # blocks until the client closes
            log.info("League client connection lost; will reconnect")
            self._popup_request("hide")
            self._stopping.wait(5)

    def _on_phase(self, phase: str) -> None:
        log.info("Gameflow phase: %s", phase)
        if phase in LOBBY_PHASES:
            self._capture_premades()
        if phase in LIVE_PHASES:
            self._popup_request("hide")  # F10b: never on screen during gameplay
        if phase in END_PHASES:
            self._handle_end_of_game()

    def _capture_premades(self) -> None:
        members = self._client.lobby_members() if self._client else []
        puuids = {m.get("puuid") for m in members if m.get("puuid")}
        puuids.discard(self._my_puuid)
        if puuids:
            self._premade_puuids = puuids
            log.info("Lobby premades captured: %d", len(puuids))

    def _handle_end_of_game(self) -> None:
        """Kick off capture in a worker thread.

        Never blocks the websocket event thread (a slow stats endpoint must not
        delay later phase events), and at most one capture runs at a time —
        PreEndOfGame and EndOfGame both trigger this for the same game.
        """
        if not self._capture_lock.acquire(blocking=False):
            return

        def worker():
            try:
                self._capture_game()
            finally:
                self._capture_lock.release()

        threading.Thread(target=worker, name="capture", daemon=True).start()

    def _capture_game(self) -> None:
        # Primary source: the end-of-game stats endpoint (has premade/party info).
        eol = self._await(self._client.end_of_game_stats, attempts=6)
        if eol is not None:
            game_id_str = str(eol.get("gameId", ""))
            if self._already_captured(game_id_str):
                return
            result = capture.normalize(eol, self._my_puuid, self._champ_names, self._premade_puuids)
            self._finish_capture(game_id_str, result, source="end-of-game stats")
            return

        # Fallback: the client's own match history. Works for every game type
        # (incl. bots) and persists after the stats screen is gone.
        log.info("End-of-game stats unavailable; falling back to match history")
        match = self._await(self._fresh_match_from_history, attempts=10, interval=3.0)
        if match is None:
            log.warning("Game ended but neither stats nor match history yielded it")
            return
        game_id_str = str(match.get("gameId", ""))
        result = capture.normalize_match(
            match, self._my_puuid, self._champ_names, self._premade_puuids
        )
        self._finish_capture(game_id_str, result, source="match history")

    def _fresh_match_from_history(self):
        """Latest match, unless we already have it (history can lag the game end)."""
        match_id = self._client.latest_match_id()
        if match_id is None or self._already_captured(str(match_id), record=False):
            return None
        return self._client.match_details(match_id)

    def _already_captured(self, game_id_str: str, record: bool = True) -> bool:
        if not game_id_str or game_id_str in self._processed_game_ids:
            return True
        if self.store.has_game(game_id_str):
            return True
        if record:
            self._processed_game_ids.add(game_id_str)
        return False

    def _finish_capture(self, game_id_str: str, result: dict, source: str) -> None:
        self._processed_game_ids.add(game_id_str)
        self._premade_puuids = set()
        stored_id = self.store.insert_game(result["game"], result["teammates"])
        if stored_id is None:
            log.info("Game %s already stored", game_id_str)
            return
        game = result["game"]
        log.info(
            "Captured game %s via %s: %s %s (%s)",
            game_id_str,
            source,
            game.get("champion"),
            "W" if game.get("win") else "L",
            game.get("queue_type"),
        )
        if not self.paused:
            self._popup_request("show", stored_id, _summary_line(game))

    def _await(self, fetch, attempts: int, interval: float = 2.0):
        """Retry a fetch that legitimately 404s/lags right after game end."""
        for _ in range(attempts):
            if self._stopping.is_set() or self._client is None:
                return None
            value = fetch()
            if isinstance(value, dict) and value.get("gameId"):
                return value
            time.sleep(interval)
        return None

    # ---------------- UI thread bridge ----------------

    def _popup_request(self, action: str, *args) -> None:
        self._ui_requests.put((action, args))

    def _drain_ui_requests(self) -> None:
        try:
            while True:
                action, args = self._ui_requests.get_nowait()
                if action == "show":
                    self._popup.show(*args)
                elif action == "hide":
                    self._popup.hide()
        except queue.Empty:
            pass
        if not self._stopping.is_set():
            self._root.after(100, self._drain_ui_requests)

    def _on_rate(self, game_id: int, score: int) -> None:
        self.store.set_rating(game_id, score)
        log.info("Game %d rated %d/5", game_id, score)


def _summary_line(game: dict) -> str:
    parts = [game.get("champion") or "?"]
    if game.get("win") is not None:
        parts.append("Victory" if game["win"] else "Defeat")
    if game.get("kills") is not None:
        parts.append(f"{game['kills']}/{game['deaths']}/{game['assists']}")
    if game.get("queue_type"):
        parts.append(game["queue_type"])
    return "  ·  ".join(str(p) for p in parts)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )
    App().run()
