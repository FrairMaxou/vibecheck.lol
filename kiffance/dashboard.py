"""The localhost dashboard server (PRD F13, §6b N4).

FastAPI + a static single-page frontend (kiffance/web). Binds 127.0.0.1 only.
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

from .config import DASHBOARD_HOST, DASHBOARD_PORT, WEB_DIR
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


class LoginIn(BaseModel):
    email: str
    password: str
    create: bool = False


class SquadNameIn(BaseModel):
    name: str


class InviteIn(BaseModel):
    squad_id: str


class JoinIn(BaseModel):
    code: str


def create_app(store: GameStore, squad: SquadService | None = None) -> FastAPI:
    app = FastAPI(title="League of Kiffance", docs_url=None, redoc_url=None, openapi_url=None)
    squad = squad or SquadService(store)

    # Binding to 127.0.0.1 stops remote access, but not DNS rebinding: an
    # attacker's domain can resolve to 127.0.0.1, at which point the browser
    # treats their page as same-origin with this server and CORS no longer
    # protects us. Rejecting unexpected Host headers closes that.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

    def _auto_sync() -> None:
        """Push rated games to the backend in the background after a rating."""
        if not squad.logged_in:
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
    # Opt-in: with no config these all report "not set up" and nothing leaves
    # the machine. Bound to localhost, so credentials stay on this PC.

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
            return {"configured": squad.configured, "logged_in": False, "error": str(exc)}

    @app.post("/api/squad/config")
    def squad_config(body: SquadConfigIn):
        return _guard(lambda: squad.configure(body.url, body.anon_key))

    @app.post("/api/squad/login")
    def squad_login(body: LoginIn):
        return _guard(lambda: squad.sign_in(body.email, body.password, body.create))

    @app.post("/api/squad/logout")
    def squad_logout():
        return _guard(squad.sign_out)

    @app.post("/api/squad/create")
    def squad_create(body: SquadNameIn):
        return _guard(lambda: {"squad": squad.create_squad(body.name)})

    @app.post("/api/squad/invite")
    def squad_invite(body: InviteIn):
        return _guard(lambda: {"code": squad.create_invite(body.squad_id)})

    @app.post("/api/squad/join")
    def squad_join(body: JoinIn):
        return _guard(lambda: {"squad_id": squad.join_squad(body.code)})

    @app.post("/api/squad/push")
    def squad_push():
        return _guard(lambda: {"synced": squad.push()})

    @app.get("/api/squad/{squad_id}/data")
    def squad_data(squad_id: str):
        return _guard(lambda: squad.squad_games(squad_id))

    return app


def start_dashboard(store: GameStore, squad: SquadService | None = None) -> str:
    """Start the server in a daemon thread; returns the dashboard URL."""
    config = uvicorn.Config(
        create_app(store, squad),
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
