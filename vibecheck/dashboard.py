"""The localhost dashboard server (PRD F13, §6b N4).

FastAPI + a static single-page frontend (vibecheck/web). Binds 127.0.0.1 only.
All data access goes through the GameStore; the frontend does filtering and
aggregation client-side, which is what makes the filter bar and explorer
(F13b/F13c) instant.
"""

import logging
import threading

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import startup, telemetry, updater, whatsnew
from .config import (
    APP_NAME,
    APP_VERSION,
    ASSETS_DIR,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DATA_DIR,
    DISCORD_INVITE_URL,
    WEB_DIR,
    feedback_form_url,
)
from .store import GameStore
from .sync import SquadService, SupabaseError

log = logging.getLogger(__name__)

STATIC_FILES = {"app.js", "style.css", "chart.umd.js"}
# Brand assets the dashboard is allowed to serve. Allowlisted for the same
# reason as STATIC_FILES: `name` comes from the URL, so nothing else in
# ASSETS_DIR (the meme rating art, for one) can be reached by guessing.
ASSET_FILES = {"logo-horizontal.png", "logo.png", "logo.ico"}

LAST_SEEN_VERSION_KEY = "last_seen_version"  # drives the once-per-update notes


class RatingIn(BaseModel):
    score: int | None = None
    skipped: bool = False


class TagsIn(BaseModel):
    tags: list[str] = []


class NoteIn(BaseModel):
    note: str = ""


class SquadConfigIn(BaseModel):
    url: str
    anon_key: str


class SettingsIn(BaseModel):
    autostart: bool | None = None
    paused: bool | None = None
    close_action: str | None = None  # "ask" | "minimize" | "quit"
    telemetry: bool | None = None


def create_app(
    store: GameStore, squad: SquadService | None = None, controls: dict | None = None
) -> FastAPI:
    app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
    squad = squad or SquadService(store)
    controls = controls or {}
    update_job = updater.UpdateJob()

    def _settings() -> dict:
        is_paused = controls.get("is_paused")
        return {
            "autostart": startup.is_enabled(),
            "paused": bool(is_paused()) if is_paused else False,
            "autostart_supported": startup.winreg is not None,
            "close_action": store.get_meta("close_action") or "ask",
            "summoner_name": store.get_meta("my_summoner_name"),
            "version": APP_VERSION,
            "discord_url": DISCORD_INVITE_URL,
            # Empty until a form exists — the UI hides the entry rather than
            # offering a link that goes nowhere.
            "feedback_url": feedback_form_url(),
            "telemetry": telemetry.is_enabled(store),
        }

    # Binding to 127.0.0.1 stops remote access, but not DNS rebinding: an
    # attacker's domain can resolve to 127.0.0.1, at which point the browser
    # treats their page as same-origin with this server and CORS no longer
    # protects us. Rejecting unexpected Host headers closes that.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def _auto_sync() -> None:
        """Push rated games to the backend in the background after a rating."""
        if not squad.configured:
            return

        def worker():
            try:
                squad.push()
            except SupabaseError:
                log.warning("Background squad sync failed (will retry next rating)")

        threading.Thread(target=worker, name="squad-sync", daemon=True).start()

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/static/{name}")
    def static(name: str):
        if name not in STATIC_FILES:  # allowlist — no path traversal possible
            raise HTTPException(404)
        return FileResponse(WEB_DIR / name)

    @app.get("/assets/{name}")
    def asset(name: str):
        """Brand assets (logo, favicon). Same allowlist guard as /static."""
        if name not in ASSET_FILES:
            raise HTTPException(404)
        return FileResponse(ASSETS_DIR / name)

    @app.get("/api/games")
    def games():
        return {"games": store.games_with_details()}

    @app.get("/api/rev")
    def rev():
        """Cheap poll target: the dashboard only re-fetches /api/games when this
        changes, instead of blindly refreshing on a timer (which caused a visible
        flash and made freshly-rated games sit in "To Rate" until the next tick)."""
        return {"rev": store.data_revision()}

    @app.post("/api/games/{game_id}/rating")
    def rate(game_id: int, body: RatingIn):
        if not body.skipped and (body.score is None or not 1 <= body.score <= 5):
            raise HTTPException(422, "score must be 1..5 (or skipped)")
        store.set_rating(game_id, None if body.skipped else body.score, skipped=body.skipped)
        log.info(
            "Dashboard rating: game %d -> %s", game_id, "skipped" if body.skipped else body.score
        )
        _auto_sync()
        # Hand back the new rev so the frontend's optimistic update can adopt it
        # directly instead of triggering a second, redundant full re-fetch.
        return {"ok": True, "rev": store.data_revision()}

    @app.get("/api/settings")
    def get_settings():
        return _settings()

    @app.post("/api/settings")
    def update_settings(body: SettingsIn):
        if body.autostart is not None:
            startup.set_enabled(body.autostart)
        if body.paused is not None and controls.get("set_paused"):
            controls["set_paused"](body.paused)
        if body.close_action in ("ask", "minimize", "quit"):
            store.set_meta("close_action", body.close_action)
        if body.telemetry is not None:
            telemetry.set_enabled(store, body.telemetry)
        return _settings()

    @app.post("/api/quit")
    def quit_app():
        """Shut the whole app down (used by the window's close prompt)."""
        quit_fn = controls.get("quit")
        if not quit_fn:
            return {"ok": True, "quitting": False}
        # Respond first, then stop — calling it inline would tear down the
        # server mid-response. A short timer lets this request return cleanly.
        threading.Timer(0.3, quit_fn).start()
        return {"ok": True, "quitting": True}

    def _update_info(force: bool = False) -> dict:
        # Cached in updater.py so the background tray check shares both the
        # answer and the rate-limit budget with this endpoint.
        return updater.check_cached(store, force)

    @app.get("/api/update")
    def check_update(force: bool = False):
        """Best-effort 'is a newer release out?' check against public releases.

        Reports update_available=False on any failure (offline, rate-limited),
        so it never nags when it can't be sure.
        """
        return {**_update_info(force), "job": update_job.snapshot()}

    @app.post("/api/update/install")
    def install_update():
        """Download, verify and swap in the new build, then relaunch."""
        info = _update_info()
        if not info.get("update_available"):
            raise HTTPException(409, "already up to date")
        if not info.get("can_self_update"):
            raise HTTPException(
                409, "this build can't update itself — download it from the releases page"
            )
        if update_job.running:
            return {"ok": True, "job": update_job.snapshot()}

        def restart():
            # The new process is already starting and waits on our PID, so all
            # that's left is to get out of its way.
            quit_fn = controls.get("quit")
            if quit_fn:
                threading.Timer(0.5, quit_fn).start()

        update_job.start(info, restart)
        return {"ok": True, "job": update_job.snapshot()}

    @app.get("/api/update/progress")
    def update_progress():
        return update_job.snapshot()

    @app.post("/api/uninstall")
    def uninstall():
        """Remove the start-with-Windows entry; report what to delete manually.

        A portable single-exe can't delete its own running file, so the only
        persistent trace we own is the autostart registry key — we clear that
        and hand back the paths for the user to remove.
        """
        startup.set_enabled(False)
        return {"ok": True, "data_dir": str(DATA_DIR)}

    @app.get("/api/whats-new")
    def whats_new():
        """The "what changed" notes, shown once after an update.

        Deliberately silent on a fresh install: someone opening VibeCheck for
        the first time has nothing to catch up on. That first run just records
        the current version so the *next* update is the one that speaks up.
        """
        seen = store.get_meta(LAST_SEEN_VERSION_KEY)
        if seen is None:
            store.set_meta(LAST_SEEN_VERSION_KEY, APP_VERSION)
            return {"version": APP_VERSION, "notes": [], "show": False}
        notes = whatsnew.notes_for(APP_VERSION)
        return {"version": APP_VERSION, "notes": notes, "show": bool(notes) and seen != APP_VERSION}

    @app.post("/api/whats-new/seen")
    def whats_new_seen():
        store.set_meta(LAST_SEEN_VERSION_KEY, APP_VERSION)
        return {"ok": True}

    @app.get("/api/tags")
    def tags():
        return {"tags": store.list_tags()}

    @app.post("/api/games/{game_id}/tags")
    def set_tags(game_id: int, body: TagsIn):
        store.set_game_tags(game_id, body.tags)
        return {"ok": True}

    @app.post("/api/games/{game_id}/note")
    def set_note(game_id: int, body: NoteIn):
        store.set_note(game_id, body.note)
        return {"ok": True}

    # ---------------- squad / social (§12) ----------------
    # Zero-config: released builds bundle the backend, identity is the in-game
    # PUUID, and the squad is your mutual League friends. No login, no codes.
    # With no backend configured these report "not set up" and nothing leaves
    # the machine. Bound to localhost, so any credentials stay on this PC.

    def _guard(fn):
        try:
            return {"ok": True, **(fn() or {})}
        except SupabaseError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/squad/status")
    def squad_status():
        try:
            return squad.status()
        except SupabaseError as exc:
            return {"configured": squad.configured, "identity_ready": False, "error": str(exc)}

    @app.post("/api/squad/config")
    def squad_config(body: SquadConfigIn):
        # Advanced / self-host only — released builds never hit this.
        return _guard(lambda: squad.configure(body.url, body.anon_key))

    @app.post("/api/squad/push")
    def squad_push():
        return _guard(lambda: {"synced": squad.push()})

    @app.get("/api/squad/data")
    def squad_data():
        return _guard(squad.friends_games)

    return app


def start_dashboard(
    store: GameStore, squad: SquadService | None = None, controls: dict | None = None
) -> str:
    """Start the server in a daemon thread; returns the dashboard URL."""
    config = uvicorn.Config(
        create_app(store, squad, controls),
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        log_level="warning",
        # log_config=None: don't let uvicorn run its own logging dictConfig — its
        # formatter calls sys.stdout.isatty(), which crashes under pythonw (no
        # console → sys.stdout is None). We use the root logger already set up.
        log_config=None,
    )
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, name="dashboard", daemon=True).start()
    url = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
    log.info("Dashboard serving at %s", url)
    return url
