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

from . import startup
from .config import APP_NAME, DASHBOARD_HOST, DASHBOARD_PORT, WEB_DIR
from .store import GameStore
from .sync import SquadService, SupabaseError

log = logging.getLogger(__name__)

STATIC_FILES = {"app.js", "style.css", "chart.umd.js"}


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


def create_app(
    store: GameStore, squad: SquadService | None = None, controls: dict | None = None
) -> FastAPI:
    app = FastAPI(title=APP_NAME, docs_url=None, redoc_url=None, openapi_url=None)
    squad = squad or SquadService(store)
    controls = controls or {}

    def _settings() -> dict:
        is_paused = controls.get("is_paused")
        return {
            "autostart": startup.is_enabled(),
            "paused": bool(is_paused()) if is_paused else False,
            "autostart_supported": startup.winreg is not None,
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

    @app.get("/api/games")
    def games():
        return {"games": store.games_with_details()}

    @app.post("/api/games/{game_id}/rating")
    def rate(game_id: int, body: RatingIn):
        if not body.skipped and (body.score is None or not 1 <= body.score <= 5):
            raise HTTPException(422, "score must be 1..5 (or skipped)")
        store.set_rating(game_id, None if body.skipped else body.score, skipped=body.skipped)
        log.info(
            "Dashboard rating: game %d -> %s", game_id, "skipped" if body.skipped else body.score
        )
        _auto_sync()
        return {"ok": True}

    @app.get("/api/settings")
    def get_settings():
        return _settings()

    @app.post("/api/settings")
    def update_settings(body: SettingsIn):
        if body.autostart is not None:
            startup.set_enabled(body.autostart)
        if body.paused is not None and controls.get("set_paused"):
            controls["set_paused"](body.paused)
        return _settings()

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
