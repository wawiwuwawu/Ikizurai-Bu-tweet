"""Entrypoint: FastAPI + worker thread + serve frontend build."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import db as dbm
from .api import router
from .config import get_settings
from .worker import Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("ikizurai.main")

FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


def _start_worker(app: FastAPI) -> None:
    settings = app.state.settings

    def _run() -> None:
        try:
            # koneksi SQLite WAJIB dibuat di thread ini (sqlite3 thread-affine)
            worker = Worker(settings, dbm.connect(settings.db_path))
            app.state.worker = worker
            worker.run_forever()
        except Exception:  # noqa: BLE001
            log.exception("worker thread berhenti tak terduga")

    t = threading.Thread(target=_run, name="ikizurai-worker", daemon=True)
    t.start()
    log.info("Worker thread berjalan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    errors = settings.validate(require_webhook=True)
    for e in errors:
        log.warning("konfigurasi: %s", e)
    if settings.translate_paused:
        log.info("Translasi di-pause (TRANSLATE_PAUSED=true)")
    if settings.worker_enabled:
        _start_worker(app)
    else:
        log.info("Worker dimatikan (WORKER_ENABLED=false)")
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Ikizurai-Bu Tweet Archive", version="1.0.0", lifespan=lifespan)
    app.state.settings = settings
    dbm.init_db(dbm.connect(settings.db_path))

    app.include_router(router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # Sajikan build frontend bila ada (produksi)
    if FRONTEND_DIST.exists():
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):  # SPA fallback
            index = FRONTEND_DIST / "index.html"
            target = FRONTEND_DIST / full_path
            if full_path and target.is_file():
                return FileResponse(target)
            return FileResponse(index)

    return app


app = create_app()


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
