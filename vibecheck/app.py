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

from . import capture, config, lcu, startup, telemetry, updater
from .config import (
    APP_NAME,
    ASSETS_CHAMPS_KEY,
    CATCHUP_FIRST_RUN_HOURS,
    CLIENT_POLL_SECONDS,
    DATA_DIR,
    FROZEN,
    LOG_PATH,
    QUEUE_LABELS_VERSION,
)
from .dashboard import start_dashboard
from .popup import RatingPopup
from .store import GameStore
from .sync import SquadService
from .tray import build_tray, notify

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
QUEUE_LABELS_KEY = "queue_labels_version"
PREMADES_KEY = "lobby_premades"  # survives a mid-game restart
UPDATE_NOTIFIED_KEY = "update_notified"  # version we've already toasted about
ONBOARDING_KEY = "onboarding_state"  # "backfilled" once imported, "done" once dismissed
ONBOARDING_GAMES = 5  # == PRD MIN_N, so rating them all clears "not enough data yet"

UPDATE_CHECK_DELAY_SECONDS = 90  # let startup finish first
UPDATE_CHECK_INTERVAL_SECONDS = 6 * 3600  # matches the updater's cache TTL
PENDING_RESOLUTION_INTERVAL_SECONDS = 5 * 60  # #96: Arena sync lag measured 3-10+ min live
PREMADES_MAX_AGE_HOURS = 6


class App:
    def __init__(self):
        self.store = GameStore()
        # First launch: don't backfill history beyond a short grace window.
        if self.store.get_meta(WATERMARK_KEY) is None:
            grace = datetime.now() - timedelta(hours=CATCHUP_FIRST_RUN_HOURS)
            self.store.set_meta(WATERMARK_KEY, grace.isoformat(timespec="seconds"))
        self.paused = False
        self._stopping = threading.Event()
        self._stop_lock = threading.Lock()  # makes stop()'s check-and-set atomic
        self._ui_requests: queue.Queue = queue.Queue()

        self._client: lcu.LcuClient | None = None
        self._events: lcu.GameflowEvents | None = None
        self._my_puuid: str | None = None
        self._champ_names: dict = {}
        self._assets: dict = {}
        self._premade_puuids: set = set()
        self._restore_premades()  # a restart mid-game must not lose the lobby
        self._processed_game_ids: set = set()
        self._capture_lock = threading.Lock()

        self._root = tk.Tk()
        self._root.withdraw()
        # Quit when Windows is shutting down, or the user gets an "app is
        # preventing shutdown" screen naming VibeCheck. The X11-era protocol
        # name is not a mistake: on Windows, Tk intercepts WM_QUERYENDSESSION
        # and re-raises it as WM_SAVE_YOURSELF (tkWinWm.c), which it then drops
        # unless a handler is registered. A withdrawn root still receives it —
        # Windows sends session messages to hidden top-level windows too.
        self._root.protocol("WM_SAVE_YOURSELF", self.stop)
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
        # Set by the background check; drives the tray's "Update to vX.Y.Z" entry.
        self._pending_update: str | None = None
        self._tray = build_tray(
            on_quit=self.stop,
            on_open_dashboard=self._open_dashboard,
            on_update=self._open_update,
            pending_version=lambda: self._pending_update,
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
        self._start_update_check()
        self._start_pending_resolution()
        self._relabel_queues()
        self._root.mainloop()

    def _relabel_queues(self) -> None:
        """Re-apply queue names to already-captured games after the label table
        changes (F3b). Labels are written at capture time, so a game played
        before its mode had a name keeps the raw one — League Classic games
        captured at launch read "JADE" until this runs.

        Runs once per QUEUE_LABELS_VERSION bump, off the main thread because it
        reads every stored payload. Each update bumps the store revision, so an
        open dashboard picks the new names up on its own.
        """
        if self.store.get_meta(QUEUE_LABELS_KEY) == str(QUEUE_LABELS_VERSION):
            return

        def worker():
            fixed = 0
            try:
                for row in self.store.games_with_raw():
                    try:
                        payload = json.loads(row["raw_payload"])
                    except (TypeError, ValueError):
                        continue
                    if not isinstance(payload, dict):
                        continue
                    label = capture.queue_label(row["queue_id"], payload)
                    if label and label != row["queue_type"]:
                        self.store.update_queue_type(row["id"], label)
                        fixed += 1
                self.store.set_meta(QUEUE_LABELS_KEY, str(QUEUE_LABELS_VERSION))
                if fixed:
                    log.info("Re-labelled %d game(s) with updated queue names", fixed)
            except Exception:
                # Cosmetic only — never let it stop the app, and leave the
                # version unset so it retries next launch.
                log.exception("Queue relabel pass failed")

        threading.Thread(target=worker, name="queue-relabel", daemon=True).start()

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

    def _start_update_check(self) -> None:
        """Look for new releases in the background, not just when the dashboard
        is open.

        Most people run VibeCheck as a tray icon and never open the dashboard,
        so a release could sit unnoticed indefinitely — the check that mattered
        only ran when the profile menu was opened. This surfaces it instead: a
        balloon once per version, plus a tray entry that stays until taken.

        Still never silent (PRD §9): finding an update only offers it, and the
        install is the same one-click flow the user drives from the dashboard.
        """

        def worker():
            if self._stopping.wait(UPDATE_CHECK_DELAY_SECONDS):
                return  # quit before the delay elapsed
            while not self._stopping.is_set():
                try:
                    self._check_for_update()
                except Exception:
                    # Offline, rate-limited, GitHub down — all fine, try later.
                    log.debug("Background update check failed", exc_info=True)
                if self._stopping.wait(UPDATE_CHECK_INTERVAL_SECONDS):
                    return

        threading.Thread(target=worker, name="update-check", daemon=True).start()

    def _start_pending_resolution(self) -> None:
        """Safety net for #96: catch-up only re-checks on the next lobby
        visit or reconnect, and Arena's sync lag (measured 3-10+ minutes)
        routinely outlasts a single lobby visit. This sweeps on its own
        schedule instead, but stays cheap when idle — it only touches the
        LCU when the store actually has an unresolved row.
        """

        def worker():
            while not self._stopping.is_set():
                if self._stopping.wait(PENDING_RESOLUTION_INTERVAL_SECONDS):
                    return
                if not self.store.unresolved_games():
                    continue
                if not self._capture_lock.acquire(blocking=False):
                    continue  # a capture/catch-up is already using the client
                try:
                    self._resolve_pending_games()
                except Exception:
                    log.exception("Pending-game resolution sweep failed")
                finally:
                    self._capture_lock.release()

        threading.Thread(target=worker, name="pending-resolve", daemon=True).start()

    def _check_for_update(self) -> None:
        info = updater.check_cached(self.store)
        latest = info.get("latest")
        if not info.get("update_available") or not latest:
            self._pending_update = None  # e.g. a release that got pulled
            return

        self._pending_update = latest
        try:
            self._tray.update_menu()  # so the entry appears without a restart
        except Exception:
            log.debug("Could not refresh the tray menu", exc_info=True)

        # The toast is once per version. The tray entry is the persistent
        # reminder — a balloon on every restart until you update would be nagging.
        if self.store.get_meta(UPDATE_NOTIFIED_KEY) == latest:
            return
        self.store.set_meta(UPDATE_NOTIFIED_KEY, latest)
        log.info("Update available: v%s", latest)
        notify(
            self._tray,
            f"{APP_NAME} v{latest} is out",
            "Open VibeCheck to install it — takes a few seconds."
            if info.get("can_self_update")
            else "Grab it from the releases page when you have a minute.",
        )

    def _open_update(self) -> None:
        """Tray "Update to vX.Y.Z": open the dashboard with the update offered.

        Deliberately not a one-click install from the tray — the user should see
        what they're installing, and the dashboard already shows progress.
        """
        self._open_dashboard(query="?update=1")

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
        """Tear the app down. Safe to call from any thread, and more than once.

        Four paths reach this, on three different threads: the tray's Quit
        entry (tray thread), the dashboard window's close prompt and the
        self-updater's restart (both server-side timers), and the Windows
        shutdown handler (Tk main thread). Two can fire at once — a session-end
        message arriving while someone clicks Quit, or while an update is
        swapping the build — so the check-and-set is under a lock. A bare Event
        is not enough: both callers could pass is_set() before either reached
        set(), and run the teardown twice from two threads.
        """
        with self._stop_lock:
            if self._stopping.is_set():
                return
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

    def _open_dashboard(self, query: str = "") -> None:
        """Open the dashboard in its own native window process (§14).

        `query` deep-links into a part of the UI (e.g. "?update=1" opens the
        profile menu on the update). It's ignored when a window is already open,
        which is fine — the user is looking at the app either way.
        """
        if self._window_proc is not None and self._window_proc.poll() is None:
            log.info("Dashboard window already open")
            return
        url = self._dashboard_url + query
        # Frozen builds have no `python -m`, so the exe relaunches itself with a
        # flag that run_vibecheck.py routes to the window (see that module).
        argv = (
            [sys.executable, "--window", url]
            if FROZEN
            else [sys.executable, "-m", "vibecheck.window", url]
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
        self._sync_achievements()
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

    def _sync_achievements(self) -> None:
        """Refresh ARAM God progress from the client's challenge data (PRD §16).

        Read on every client connect rather than after every game: the client
        recomputes the challenge itself, and a game that completes a new
        champion is reflected the next time we connect at the latest. Cheap
        enough to do inline here — one local GET the watcher is already making
        four of.

        Never destructive. A read that fails leaves the stored set alone, so
        launching with the client closed, or Riot retiring the challenge, shows
        the last known progress instead of wiping a lifetime figure VibeCheck
        has no way to rebuild.
        """
        try:
            completed = self._client.completed_champion_ids(config.ARAM_GOD_CHALLENGE_ID)
        except Exception:
            log.warning("Could not read challenge progress", exc_info=True)
            return
        if completed is None:
            log.info("ARAM God progress unavailable from the client — keeping what we have")
            return
        changed = self.store.set_achievement_champions(
            config.ARAM_GOD_KEY, completed, source="client"
        )
        log.info(
            "ARAM God: %d champion(s) completed%s",
            len(completed),
            "" if changed else " (unchanged)",
        )

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
            # Persist it: the lobby is gone by the time the game ends, so if the
            # app restarts mid-game an in-memory-only set is lost and the game
            # is recorded as solo queue. Survives that.
            self.store.set_meta(
                PREMADES_KEY,
                json.dumps(
                    {"at": datetime.now().isoformat(timespec="seconds"), "puuids": list(puuids)}
                ),
            )
            log.info("Lobby premades captured: %d", len(puuids))

    def _restore_premades(self) -> None:
        """Reload the last lobby snapshot after a restart (see _capture_premades).

        Only a recent one: an old snapshot belongs to a session that's long over,
        and wrongly tagging a later solo game as premade would quietly corrupt
        the Squad Buff comparison.
        """
        try:
            saved = json.loads(self.store.get_meta(PREMADES_KEY) or "{}")
            when = datetime.fromisoformat(saved["at"])
            puuids = {p for p in saved.get("puuids", []) if p}
        except (ValueError, KeyError, TypeError):
            return
        if not puuids or datetime.now() - when > timedelta(hours=PREMADES_MAX_AGE_HOURS):
            return
        self._premade_puuids = puuids
        log.info("Restored %d lobby premade(s) from the previous run", len(puuids))

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

    def _known_game_id(self) -> int | None:
        """The authoritative id for the game that's ending, straight from the
        live gameflow session (issue #96) — available immediately after
        PreEndOfGame/EndOfGame, well before Riot's local match-history cache
        has synced it. Using this instead of guessing the "newest" entry in
        recent_matches() is what makes the match-history lookup exact rather
        than order- and timing-dependent, which is what actually broke Arena
        capture (a stale "newest" id can win for the entire retry window).
        """
        if self._client is None:
            return None
        session = self._client.gameflow_session() or {}
        game_id = (session.get("gameData") or {}).get("gameId")
        return game_id if isinstance(game_id, int) and game_id > 0 else None

    def _capture_game(self) -> None:
        known_game_id = self._known_game_id()

        # Primary source: the end-of-game stats endpoint (has premade/party info).
        eol = self._await(self._client.end_of_game_stats, attempts=6, label="end_of_game_stats")
        if eol is not None:
            game_id_str = str(eol.get("gameId", ""))
            if self._already_captured(game_id_str):
                return
            result = capture.normalize(
                eol, self._my_puuid, self._champ_names, self._premade_puuids, self._assets
            )
            self._finish_capture(game_id_str, result, source="end-of-game stats")
            return

        # Fallback: the client's own match history. Look it up by the id we
        # already know from the live gameflow session when we have one —
        # exact, not a guess — falling back to the old "newest in
        # recent_matches()" heuristic only if that id is somehow unavailable.
        log.info("End-of-game stats unavailable; falling back to match history")
        if known_game_id is not None:
            match = self._await(
                lambda: self._client.match_details(known_game_id),
                attempts=10,
                interval=3.0,
                label="match_history",
            )
        else:
            match = self._await(
                self._fresh_match_from_history, attempts=10, interval=3.0, label="match_history"
            )
        if match is not None:
            game_id_str = str(match.get("gameId", ""))
            result = capture.normalize_match(
                match, self._my_puuid, self._champ_names, self._premade_puuids, self._assets
            )
            self._finish_capture(game_id_str, result, source="match history")
            return

        if known_game_id is None:
            log.warning("Game ended but neither stats nor match history yielded it")
            return

        # Match history hasn't synced yet — measured 3-10+ minutes for Arena
        # (#96), well past any reasonable live retry window. Ask for the
        # rating now, while it's fresh, and resolve the real stats
        # asynchronously once the client's history catches up.
        self._create_pending_capture(known_game_id)

    def _start_catch_up(self) -> None:
        """Import finished games we missed (F6), in the capture worker slot."""
        if not self._capture_lock.acquire(blocking=False):
            return  # a capture/catch-up is already running

        def worker():
            try:
                # Before the normal sweep: the backfill advances the watermark,
                # so catch-up then correctly sees those games as already ours
                # and doesn't pop a rating prompt for one of them.
                self._backfill_for_onboarding()
                self._catch_up()
                self._resolve_pending_games()
            except Exception:
                log.exception("Catch-up sweep failed")
            finally:
                self._capture_lock.release()

        threading.Thread(target=worker, name="catch-up", daemon=True).start()

    def _backfill_for_onboarding(self) -> None:
        """First install only: import recent games so the dashboard isn't empty.

        A new user opens VibeCheck to blank charts and the next game is half an
        hour away, which is a poor reason to close it and not come back. Pulling
        the last few games gives the dashboard something to show and the user
        something to rate right now.

        Deliberately silent — no rating popup. These land in "To Rate" and the
        dashboard offers them as a one-time wizard; firing five popups at a
        first-time user would be the opposite of a welcome.
        """
        if self.store.get_meta(ONBOARDING_KEY) or self.store.game_count():
            return
        self.store.set_meta(ONBOARDING_KEY, "backfilled")  # once, even if it finds nothing

        imported = 0
        for summary in sorted(
            self._client.recent_matches(ONBOARDING_GAMES),
            key=lambda g: g.get("gameCreation", 0),
        ):  # oldest first, so session numbering stays chronological
            game_id = summary.get("gameId")
            if not game_id or self.store.has_game(str(game_id)):
                continue
            match = self._client.match_details(game_id) or summary
            result = capture.normalize_match(
                match, self._my_puuid, self._champ_names, set(), self._assets
            )
            if result["game"].get("is_remake"):
                continue  # F5: never ask about a remake
            if self.store.insert_game(result["game"], result["teammates"]) is not None:
                self._advance_watermark(result["game"].get("played_at", ""))
                imported += 1
        log.info("Onboarding backfill imported %d recent game(s)", imported)

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
        if match_id is None:
            # DIAGNOSTIC (issue #96): distinguishes "history hasn't synced the
            # game yet" from "history has it but match_details is unusable".
            log.info("_fresh_match_from_history: recent_matches() has no games yet")
            return None
        if self._already_captured(str(match_id), record=False):
            log.info("_fresh_match_from_history: latest game %s already captured", match_id)
            return None
        match = self._client.match_details(match_id)
        if match is not None and not (isinstance(match, dict) and match.get("gameId")):
            log.info(
                "_fresh_match_from_history: match_details(%s) returned %s without gameId: %s",
                match_id,
                type(match).__name__,
                json.dumps(match, default=str)[:2000],
            )
        return match

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
        self.store.set_meta(PREMADES_KEY, "")  # consumed — don't reuse next game
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

    def _create_pending_capture(self, game_id: int) -> None:
        """Two-phase capture for a game whose match history hasn't synced yet
        (issue #96 — Arena regularly takes minutes, not seconds). Ask how it
        went right now, while the moment is fresh, and let
        _resolve_pending_games fill in the real stats later.

        premade_puuids is snapshotted into the stub itself: self._premade_puuids
        is a single shared slot that the *next* lobby's ChampSelect overwrites,
        and that routinely happens before this game resolves.
        """
        game_id_str = str(game_id)
        if self._already_captured(game_id_str):
            return
        played_at = datetime.now().isoformat(timespec="seconds")
        stored_id = self.store.insert_pending_game(game_id_str, played_at, self._premade_puuids)
        self._premade_puuids = set()
        self.store.set_meta(PREMADES_KEY, "")
        if stored_id is None:
            log.info("Pending game %s already stored", game_id_str)
            return
        self._advance_watermark(played_at)
        log.info("Game %s not synced yet; asking for a rating now, stats to follow", game_id_str)
        if not self.paused:
            self._popup_request("show", stored_id, "Stats are still syncing — rate it now")

    def _resolve_pending_games(self) -> None:
        """Complete any pending stub whose match history has caught up.

        Caller must already hold self._capture_lock (see _start_catch_up and
        _start_pending_resolution, the two callers).
        """
        if self._client is None:
            return
        for row in self.store.unresolved_games():
            match = self._client.match_details(int(row["riot_match_id"]))
            if not (isinstance(match, dict) and match.get("gameId")):
                age = datetime.now() - datetime.fromisoformat(row["played_at"])
                if age > timedelta(hours=24):
                    log.warning(
                        "Pending game %s still unresolved after %s — Riot may never "
                        "have synced this one; the rating is kept, stats stay blank",
                        row["riot_match_id"],
                        age,
                    )
                continue
            premades = set(json.loads(row["pending_premades"] or "[]"))
            result = capture.normalize_match(
                match, self._my_puuid, self._champ_names, premades, self._assets
            )
            if self.store.complete_game(row["id"], result["game"], result["teammates"]):
                log.info(
                    "Resolved pending game %s: %s (%s)",
                    row["riot_match_id"],
                    result["game"].get("champion"),
                    result["game"].get("queue_type"),
                )

    def _await(self, fetch, attempts: int, interval: float = 2.0, label: str = ""):
        """Retry a fetch that legitimately 404s/lags right after game end."""
        for attempt in range(attempts):
            if self._stopping.is_set() or self._client is None:
                return None
            value = fetch()
            if isinstance(value, dict) and value.get("gameId"):
                return value
            # DIAGNOSTIC (issue #96): a 200 with no usable gameId is a silent
            # failure mode `get()` never logs. Dump the shape so a live Arena
            # repro tells us whether the payload lacks gameId entirely or
            # nests it differently. Remove once #96 is understood/fixed.
            if value is not None:
                log.info(
                    "_await(%s) attempt %d: got %s without a usable gameId: %s",
                    label or getattr(fetch, "__name__", "?"),
                    attempt + 1,
                    type(value).__name__,
                    json.dumps(value, default=str)[:2000],
                )
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
        # Both names are claimed: the pre-rebrand one is what builds up to
        # v0.1.8 hold, and a user who launches an old exe alongside this one
        # must still be told, not left with two instances fighting over the
        # port and DB. The handles are deliberately never closed — Windows
        # frees them when the process dies, crash included.
        already = False
        for name in ("Local\\VibeCheck_singleton", "Local\\LeagueOfKiffance_singleton"):
            kernel32.CreateMutexW(None, False, name)
            already = already or ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
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
    # config.py migrates the pre-rebrand data folder at import time, before any
    # handler exists. Replay what it did now, so a failed move is visible in the
    # log instead of looking like missing history.
    for note in config.DATA_MIGRATION_NOTES:
        log.info("Data location: %s", note)
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
