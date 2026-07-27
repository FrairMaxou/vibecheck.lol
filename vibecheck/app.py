"""Orchestration: threads, gameflow handling, and the Tk main loop.

Threading model:
- main thread: hidden Tk root + RatingPopup (Tk requires the main thread);
  drains a queue of UI requests posted by other threads.
- watcher thread: finds the League client, then blocks on the LCU WebSocket
  (event-driven, no polling while connected) and reconnects if the client exits.
- tray thread: pystray icon.
"""

import json
import logging
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from tkinter import messagebox

from . import capture, lcu, startup, telemetry, updater
from .config import (
    APP_NAME,
    CATCHUP_FIRST_RUN_HOURS,
    CLIENT_POLL_SECONDS,
    DATA_DIR,
    FROZEN,
    LOG_PATH,
)
from .dashboard import start_dashboard
from .popup import RatingPopup
from .store import GameStore
from .sync import SquadService
from .tray import build_tray

log = logging.getLogger(__name__)

# Gameflow phases that mean a game is (about to be) over / live.
END_PHASES = {"PreEndOfGame", "EndOfGame"}
LIVE_PHASES = {"InProgress"}
LOBBY_PHASES = {"ChampSelect", "InProgress"}
# Phases meaning "no game running" — safe moments to look for missed games (F6).
IDLE_PHASES = {"None", "Lobby"}

WATERMARK_KEY = "capture_watermark"  # ISO datetime; games started after this are ours to catch
MY_PUUID_KEY = "my_puuid"
ASSETS_ITEMS_KEY = "assets_items"
ASSETS_AUGMENTS_KEY = "assets_augments"
ASSETS_CHAMPS_KEY = "assets_champions"


class App:
    def __init__(self):
        self.store = GameStore()
        # First launch: don't backfill history beyond a short grace window.
        if self.store.get_meta(WATERMARK_KEY) is None:
            grace = datetime.now() - timedelta(hours=CATCHUP_FIRST_RUN_HOURS)
            self.store.set_meta(WATERMARK_KEY, grace.isoformat(timespec="seconds"))
        self.paused = False
        self._stopping = threading.Event()
        self._ui_requests: queue.Queue = queue.Queue()

        self._client: lcu.LcuClient | None = None
        self._events: lcu.GameflowEvents | None = None
        self._my_puuid: str | None = None
        self._champ_names: dict = {}
        self._assets: dict = {}
        self._premade_puuids: set = set()
        self._processed_game_ids: set = set()
        self._capture_lock = threading.Lock()

        self._root = tk.Tk()
        self._root.withdraw()
        # Tk swallows callback exceptions to stderr (invisible under pythonw) —
        # send them to the log instead so UI errors are never lost.
        self._root.report_callback_exception = lambda *exc: log.error(
            "Tk callback error", exc_info=exc
        )
        self._popup = RatingPopup(self._root, self._on_rate)
        # One shared squad service: the dashboard drives login/squads, and the
        # rating path uses the same instance to auto-sync in the background.
        self.squad = SquadService(self.store)
        # Bridge so the dashboard's Settings page can read/change app-level state
        # (this runs in the same process — the server is a daemon thread here).
        controls = {
            "is_paused": lambda: self.paused,
            "set_paused": self._set_paused,
            "quit": self.stop,  # lets the dashboard window's close prompt quit the app
        }
        self._dashboard_url = start_dashboard(self.store, self.squad, controls)
        self._window_proc: subprocess.Popen | None = None
        self._tray = build_tray(
            on_quit=self.stop,
            on_open_dashboard=self._open_dashboard,
        )

    # ---------------- lifecycle ----------------

    def run(self) -> None:
        log.info("%s starting (%d games in store)", APP_NAME, self.store.game_count())
        threading.Thread(target=self._watcher_loop, name="lcu-watcher", daemon=True).start()
        threading.Thread(target=self._tray.run, name="tray", daemon=True).start()
        self._root.after(100, self._drain_ui_requests)
        self._root.after(1500, self._maybe_prompt_autostart)  # once, after the tray is up
        # Show the dashboard on a normal (manual) launch so the user sees the app
        # rather than a silent tray icon. Skipped when Windows starts us at login
        # (--autostart), where a window popping up every boot would be annoying.
        if "--autostart" not in sys.argv:
            self._root.after(1000, self._open_dashboard)
        self._start_usage_ping()
        self._root.mainloop()

    def _start_usage_ping(self) -> None:
        """Anonymous usage ping, well after startup so it competes with nothing.

        Entirely best-effort: it is opt-out, never raises, and the app neither
        waits for it nor cares whether it succeeded.
        """

        def worker():
            if self._stopping.wait(60):
                return  # quit before the delay elapsed
            try:
                telemetry.ping(self.store)
            except Exception:
                log.debug("Usage ping failed", exc_info=True)

        threading.Thread(target=worker, name="usage-ping", daemon=True).start()

    def _maybe_prompt_autostart(self) -> None:
        """First-run only: offer launch-at-login (F23). Tray toggle changes it later."""
        if self.store.get_meta("autostart_prompted"):
            return
        self.store.set_meta("autostart_prompted", "1")
        try:
            self._root.attributes("-topmost", True)  # bring the dialog to the front
            want = messagebox.askyesno(
                APP_NAME,
                "Launch VibeCheck.lol automatically when Windows starts?\n\n"
                "You can change this anytime in the dashboard's Settings tab.",
                parent=self._root,
            )
            startup.set_enabled(bool(want))
            log.info("First-run auto-start choice: %s", want)
        except Exception:
            log.exception("Auto-start prompt failed")

    def stop(self) -> None:
        self._stopping.set()
        if self._events:
            self._events.stop()
        self._tray.stop()
        if self._window_proc is not None and self._window_proc.poll() is None:
            self._window_proc.terminate()  # don't leave the window orphaned
        self.store.close()
        # Quit Tk from its own thread.
        self._root.after(0, self._root.quit)

    def _set_paused(self, value: bool) -> None:
        self.paused = bool(value)
        log.info("Prompts %s", "paused" if self.paused else "resumed")

    def _open_dashboard(self) -> None:
        """Open the dashboard in its own native window process (§14)."""
        if self._window_proc is not None and self._window_proc.poll() is None:
            log.info("Dashboard window already open")
            return
        # Frozen builds have no `python -m`, so the exe relaunches itself with a
        # flag that run_vibecheck.py routes to the window (see that module).
        argv = (
            [sys.executable, "--window", self._dashboard_url]
            if FROZEN
            else [sys.executable, "-m", "vibecheck.window", self._dashboard_url]
        )
        try:
            self._window_proc = subprocess.Popen(argv)  # noqa: S603 - fixed argv, no shell
            log.info("Opened dashboard window (pid %d)", self._window_proc.pid)
        except Exception:
            log.exception("Could not launch the dashboard window; using the browser")
            webbrowser.open(self._dashboard_url)

    # ---------------- watcher thread ----------------

    def _watcher_loop(self) -> None:
        # This loop must run for the whole life of the app. Any error in a single
        # connect/reconnect cycle is logged and retried — a hiccup while the
        # client restarts or the socket drops can never kill the watcher.
        while not self._stopping.is_set():
            try:
                self._watch_once()
            except Exception:
                log.exception("Watcher cycle failed; retrying in %ss", CLIENT_POLL_SECONDS)
                self._stopping.wait(CLIENT_POLL_SECONDS)

    def _watch_once(self) -> None:
        conn = lcu.discover()
        if conn is None:
            self._stopping.wait(CLIENT_POLL_SECONDS)
            return

        self._client = lcu.LcuClient(conn)
        summoner = self._client.current_summoner()
        if not summoner or "puuid" not in summoner:
            # Client process is up but the API isn't ready yet.
            self._stopping.wait(CLIENT_POLL_SECONDS)
            return
        self._my_puuid = summoner["puuid"]
        self.store.set_meta(MY_PUUID_KEY, self._my_puuid)  # lets offline tools identify you
        display_name = summoner.get("gameName") or summoner.get("displayName") or ""
        if display_name:
            self.store.set_meta("my_summoner_name", display_name)  # squad profile (§12)
        self._champ_names = self._client.champion_names()
        self._load_assets()
        log.info(
            "Connected to League client (summoner: %s)",
            summoner.get("gameName") or summoner.get("displayName", "?"),
        )
        self._sync_friends()  # zero-config squads (§12): mirror the friends list

        # Catch games that ended while we weren't listening (F6): a game still on
        # its stats screen, or finished games missed entirely (app not running,
        # game crash, client restart).
        phase = self._client.gameflow_phase()
        log.info("Current gameflow phase at connect: %s", phase or "unknown")
        if phase in LIVE_PHASES:
            log.info("A game is in progress — it will be captured when it ends")
        if phase in END_PHASES:
            self._handle_end_of_game()
        self._start_catch_up()

        self._events = lcu.GameflowEvents(conn, self._on_phase)
        self._events.run()  # blocks until the client closes
        log.info("League client connection lost; will reconnect")
        self._popup_request("hide")
        self._stopping.wait(5)

    def _on_phase(self, phase: str) -> None:
        # Runs on the websocket thread — must not raise, or the socket callback dies.
        try:
            self._dispatch_phase(phase)
        except Exception:
            log.exception("Error handling gameflow phase %s", phase)

    def _dispatch_phase(self, phase: str) -> None:
        log.info("Gameflow phase: %s", phase)
        if phase in LOBBY_PHASES:
            self._capture_premades()
        if phase in LIVE_PHASES:
            self._popup_request("hide")  # F10b: never on screen during gameplay
        if phase in END_PHASES:
            self._handle_end_of_game()
        if phase in IDLE_PHASES:
            # Back to lobby/idle: sweep for games that ended without a clean
            # EndOfGame (mid-game crash where the client survived).
            self._start_catch_up()

    def _load_assets(self) -> None:
        """Cache the client's item/augment/champion name maps (§13).

        Persisted to the store so analysis and backfill still resolve names
        when the client isn't running.
        """
        items = self._client.item_names()
        augments = self._client.augment_names()
        if items:
            self.store.set_meta(ASSETS_ITEMS_KEY, json.dumps(items))
        if augments:
            self.store.set_meta(ASSETS_AUGMENTS_KEY, json.dumps(augments))
        if self._champ_names:
            self.store.set_meta(ASSETS_CHAMPS_KEY, json.dumps(self._champ_names))
        self._assets = {"items": items, "augments": augments}
        log.info("Asset maps loaded: %d items, %d augments", len(items), len(augments))

    def _sync_friends(self) -> None:
        """Push my League friends list + rated games to the backend (§12).

        Runs in the background so the watcher can go straight to blocking on the
        gameflow socket. No-op if Squad Online isn't configured. The friends
        list is what forms squads (mutual friends), so we refresh it on every
        client connect.
        """
        if not self.squad.configured or not self._client:
            return
        client = self._client

        def worker():
            try:
                friends = client.friends()
                puuids = [f.get("puuid") for f in friends if f.get("puuid")]
                self.squad.sync_all(puuids)
            except Exception:
                log.warning("Friends sync failed (will retry next connect)", exc_info=True)

        threading.Thread(target=worker, name="friends-sync", daemon=True).start()

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
            result = capture.normalize(
                eol, self._my_puuid, self._champ_names, self._premade_puuids, self._assets
            )
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
            match, self._my_puuid, self._champ_names, self._premade_puuids, self._assets
        )
        self._finish_capture(game_id_str, result, source="match history")

    def _start_catch_up(self) -> None:
        """Import finished games we missed (F6), in the capture worker slot."""
        if not self._capture_lock.acquire(blocking=False):
            return  # a capture/catch-up is already running

        def worker():
            try:
                self._catch_up()
            except Exception:
                log.exception("Catch-up sweep failed")
            finally:
                self._capture_lock.release()

        threading.Thread(target=worker, name="catch-up", daemon=True).start()

    def _catch_up(self) -> None:
        watermark = self.store.get_meta(WATERMARK_KEY) or ""
        missed = []
        for summary in self._client.recent_matches(10):
            game_id = str(summary.get("gameId", ""))
            created_ms = summary.get("gameCreation", 0)
            if not game_id or not created_ms:
                continue
            created = datetime.fromtimestamp(created_ms / 1000).isoformat(timespec="seconds")
            if created > watermark and not self.store.has_game(game_id):
                missed.append((created, summary))
        if not missed:
            return

        missed.sort()  # oldest first, so session numbering stays chronological
        log.info("Catch-up: found %d missed game(s)", len(missed))
        newest = None
        for _, summary in missed:
            match = self._client.match_details(summary["gameId"]) or summary
            result = capture.normalize_match(
                match, self._my_puuid, self._champ_names, set(), self._assets
            )
            stored_id = self.store.insert_game(result["game"], result["teammates"])
            if stored_id is not None:
                game = result["game"]
                self._advance_watermark(game.get("played_at", ""))
                log.info(
                    "Caught up game %s: %s (%s)%s",
                    game.get("riot_match_id"),
                    game.get("champion"),
                    game.get("queue_type"),
                    " [remake]" if game.get("is_remake") else "",
                )
                if not game.get("is_remake"):  # F5: never prompt for a remake
                    newest = (stored_id, game)
        # Prompt only for the most recent one; older imports wait in pending.
        if newest is not None and not self.paused:
            self._popup_request("show", newest[0], _summary_line(newest[1]))

    def _advance_watermark(self, played_at: str) -> None:
        if played_at and played_at > (self.store.get_meta(WATERMARK_KEY) or ""):
            self.store.set_meta(WATERMARK_KEY, played_at)

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
        self._advance_watermark(result["game"].get("played_at", ""))
        if stored_id is None:
            log.info("Game %s already stored", game_id_str)
            return
        game = result["game"]
        log.info(
            "Captured game %s via %s: %s %s (%s)%s",
            game_id_str,
            source,
            game.get("champion"),
            "W" if game.get("win") else "L",
            game.get("queue_type"),
            " [remake — not prompting]" if game.get("is_remake") else "",
        )
        # F5: remakes are recorded but never rated (there was no real game).
        if not self.paused and not game.get("is_remake"):
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
                try:
                    if action == "show":
                        self._popup.show(*args)
                    elif action == "hide":
                        self._popup.hide()
                except Exception:
                    # A popup error must not break this loop — it's what keeps
                    # the whole UI thread alive.
                    log.exception("Popup %s failed", action)
        except queue.Empty:
            pass
        if not self._stopping.is_set():
            self._root.after(100, self._drain_ui_requests)

    def _on_rate(self, game_id: int, score: int) -> None:
        self.store.set_rating(game_id, score)
        log.info("Game %d rated %d/5", game_id, score)
        self._auto_sync()

    def _auto_sync(self) -> None:
        """Push rated games to the squad backend in the background (§12).

        No-op unless a backend is configured. push() creates the silent
        anonymous identity on first use — there is no login step. Runs off the
        UI thread and never raises into it: a backend hiccup must not disturb
        rating.
        """
        if not self.squad.configured:
            return

        def worker():
            try:
                self.squad.push()
            except Exception:
                log.warning("Background squad sync failed (will retry next rating)", exc_info=True)

        threading.Thread(target=worker, name="squad-sync", daemon=True).start()


def _summary_line(game: dict) -> str:
    parts = [game.get("champion") or "?"]
    if game.get("win") is not None:
        parts.append("Victory" if game["win"] else "Defeat")
    if game.get("kills") is not None:
        parts.append(f"{game['kills']}/{game['deaths']}/{game['assists']}")
    if game.get("queue_type"):
        parts.append(game["queue_type"])
    return "  ·  ".join(str(p) for p in parts)


def _install_crash_logging() -> None:
    """Route otherwise-invisible crashes to the log file.

    Under pythonw there is no console, so an uncaught exception in any thread
    would kill it silently (exactly the failure we saw: process gone, no clue
    in the log). These hooks make the cause visible next time.
    """

    def log_uncaught(exc_type, exc_value, exc_tb):
        log.critical("Uncaught exception in main thread", exc_info=(exc_type, exc_value, exc_tb))

    def log_thread_uncaught(args):
        if args.exc_type is SystemExit:
            return
        log.critical(
            "Uncaught exception in thread %s",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread_uncaught


def _acquire_single_instance() -> bool:
    """True if this is the only instance; False if one is already running.

    Uses a Windows named mutex — the OS frees it when the process dies, so
    there's no stale-lock problem after a crash. Two instances would fight over
    the port and DB and double every popup, which is exactly the confusion a
    user hits when they double-launch the exe.
    """
    try:
        import ctypes

        # use_last_error=True so ctypes.get_last_error() reflects CreateMutexW's
        # error directly — plain windll.kernel32.GetLastError() can read a stale
        # value because ctypes makes its own intervening Windows calls.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW(None, False, "Local\\LeagueOfKiffance_singleton")
        already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
        if already:
            message = (
                f"{APP_NAME} is already running.\n"
                "Check your system tray (the ^ arrow by the clock)."
            )
            ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x40)
        return not already
    except Exception:
        return True  # non-Windows / no ctypes: don't block startup


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Under pythonw there is no console, so sys.stderr is None — a StreamHandler
    # would then fail on every emit. Only add console output when a real stream
    # exists (i.e. running via `python`, not `pythonw`).
    handlers: list[logging.Handler] = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    _install_crash_logging()
    # Relaunched by the updater: the outgoing build still holds the mutex for a
    # moment, so wait for it to exit before claiming single-instance ownership.
    if "--updated-from-pid" in sys.argv:
        try:
            updater.wait_for_pid(int(sys.argv[sys.argv.index("--updated-from-pid") + 1]))
        except (ValueError, IndexError):
            log.warning("Ignoring malformed --updated-from-pid")
    if not _acquire_single_instance():
        log.warning("Another instance is already running; exiting")
        return
    updater.cleanup_old()  # drop the previous build once we're the live one
    App().run()
