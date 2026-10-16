"""FastAPI application factory.

Run with: ``uv run uvicorn ddicdi.api.main:app --reload``
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import settings
from .routes import router
from .store import UploadStore

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def create_app() -> FastAPI:
    app = FastAPI(
        title="DDI-CDI Converter API (gen2)",
        version=__version__,
        description="Converts SPSS, Stata and CSV files to DDI-CDI JSON-LD using qsv readstat.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    app.state.store = UploadStore(settings.work_dir, settings.upload_ttl_seconds)
    app.include_router(router)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    if (FRONTEND_DIST / "index.html").exists():
        # Built React editor (``cd frontend && npm run build``) served at /app.
        app.mount("/app/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="app-assets")

        @app.get("/app", include_in_schema=False)
        @app.get("/app/{path:path}", include_in_schema=False)
        def spa(path: str = "") -> FileResponse:
            candidate = FRONTEND_DIST / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST / "index.html")

        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse(url="/app/")

    else:

        @app.get("/", include_in_schema=False)
        def root_docs() -> RedirectResponse:
            return RedirectResponse(url="/docs")

    return app


app = create_app()
