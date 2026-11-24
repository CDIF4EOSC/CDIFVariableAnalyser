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
from ..images.collection import ImageStore
from .image_routes import router as image_router
from .routes import router
from .store import UploadStore

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _dist_file(dist_root: Path, path: str) -> Path | None:
    """The file under ``dist_root`` that ``path`` names, or ``None``.

    ``path`` comes straight from the URL (already percent-decoded), so it may hold
    ``..`` segments, a leading slash (an absolute path makes ``pathlib`` drop the
    root) or a NUL byte. The candidate is resolved, symlinks included, and only
    served when it is still inside the resolved dist directory.
    """
    if not path or "\x00" in path:
        return None
    try:
        candidate = (dist_root / path.lstrip("/")).resolve()
        if candidate.is_relative_to(dist_root) and candidate.is_file():
            return candidate
    except (OSError, ValueError):
        pass
    return None


def create_app(frontend_dist: Path | None = None) -> FastAPI:
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
    app.state.images = ImageStore(settings.work_dir)
    app.include_router(router)
    app.include_router(image_router)

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    dist = (frontend_dist or FRONTEND_DIST).resolve()
    if (dist / "index.html").exists():
        # Built React editor (``cd frontend && npm run build``) served at /app.
        app.mount("/app/assets", StaticFiles(directory=dist / "assets"), name="app-assets")

        @app.get("/app", include_in_schema=False)
        @app.get("/app/{path:path}", include_in_schema=False)
        def spa(path: str = "") -> FileResponse:
            # A top-level file of the build (favicon ...) or else index.html, so
            # client-side routes work; never a file outside the dist directory.
            return FileResponse(_dist_file(dist, path) or dist / "index.html")

        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse(url="/app/")

    else:

        @app.get("/", include_in_schema=False)
        def root_docs() -> RedirectResponse:
            return RedirectResponse(url="/docs")

    return app


app = create_app()
