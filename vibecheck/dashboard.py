"""The localhost dashboard server (PRD F13, §6b N4).

FastAPI + a static single-page frontend (vibecheck/web). Binds 127.0.0.1 only.
All data access goes through the GameStore; the frontend does filtering and
aggregation client-side, which is what makes the filter bar and explorer
(F13b/F13c) instant.
"""

import json
import logging
import threading
import urllib.request

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import startup
from .config import (
    APP_NAME,
    APP_VERSION,
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DATA_DIR,
    RELEASES_LATEST_API,
    RELEASES_PAGE,
    WEB_DIR,
)
from .store import GameStore
from .sync import SquadService, SupabaseError

log = logging.getLogger(__name__)

STATIC_FILES = {"app.js", "style.css", "chart.umd.js"}


def _is_newer(a: str, b: str) -> bool:
    """True if dotted version a is newer than b (e.g. '0.2.0' > '0.1.9')."""

    def parts(v: str) -> list[int]:
        out = []
        for p in v.split("."):
            digits = "".join(ch for ch in p if ch.isdigit())
            out.append(int(digits) if digits else 0)
        return out

    pa, pb = parts(a), parts(b)
    n = max(len(pa), len(pb))
    return pa + [0] * (n - len(pa)) > pb + [0] * (n - len(pb))


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
            "close_action": store.get_meta("close_action") or "ask",
            "summoner_name": store.get_meta("my_summoner_name"),
            "version": APP_VERSION,
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
        if body.close_action in ("ask", "minimize", "quit"):
            store.set_meta("close_action", body.close_action)
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

    @app.get("/api/update")
    def check_update():
        """Best-effort 'is a newer release out?' check against public releases.

        Returns update_available=False on any failure (private repo → 404,
        offline, rate-limited), so it never nags when it can't be sure.
        """
        try:
            req = urllib.request.Request(  # noqa: S310 - fixed https GitHub URL
                RELEASES_LATEST_API, headers={"Accept": "application/vnd.github+json"}
            )
            with urllib.request.urlopen(req, timeout=6) as resp:  # noqa: S310 - fixed https GitHub URL
                latest = (json.load(resp).get("tag_name") or "").lstrip("v")
        except Exception:
            return {"current": APP_VERSION, "latest": None, "update_available": False}
        return {
            "current": APP_VERSION,
            "latest": latest or None,
            "update_available": bool(latest) and _is_newer(latest, APP_VERSION),
            "url": RELEASES_PAGE,
        }

    @app.post("/api/uninstall")
    def uninstall():
        """Remove the start-with-Windows entry; report what to delete manually.

        A portable single-exe can't delete its own running file, so the only
        persistent trace we own is the autostart registry key — we clear that
        and hand back the paths for the user to remove.
        """
        startup.set_enabled(False)
        return {"ok": True, "data_dir": str(DATA_DIR)}

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
