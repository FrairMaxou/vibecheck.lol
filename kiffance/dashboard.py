"""The localhost dashboard server (PRD F13, §6b N4).

FastAPI + a static single-page frontend (kiffance/web). Binds 127.0.0.1 only.
All data access goes through the GameStore; the frontend does filtering and
aggregation client-side, which is what makes the filter bar and explorer
(F13b/F13c) instant.
"""

import logging
import threading
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import DASHBOARD_HOST, DASHBOARD_PORT
from .store import GameStore

log = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"
STATIC_FILES = {"app.js", "style.css", "chart.umd.js"}


class RatingIn(BaseModel):
    score: int | None = None
    skipped: bool = False


def create_app(store: GameStore) -> FastAPI:
    app = FastAPI(title="League of Kiffance", docs_url=None, redoc_url=None, openapi_url=None)

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
        return {"ok": True}

    return app


def start_dashboard(store: GameStore) -> str:
    """Start the server in a daemon thread; returns the dashboard URL."""
    config = uvicorn.Config(
        create_app(store),
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
