"""Security #7: waiting for an import slot holds no worker thread, and waiters are bounded."""

import asyncio
import threading
import time

import httpx
import pytest

from ddicdi.api import admission
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings


@pytest.fixture()
def app(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return app


def _hold_imports(app, monkeypatch):
    """Make every import block until the returned event is set; count bodies read."""
    release = threading.Event()
    started = []

    def blocking_create(filename, content):
        started.append(filename)
        release.wait(10)
        raise ValueError("held import")

    monkeypatch.setattr(app.state.store, "create", blocking_create)
    return release, started


def test_queued_uploads_do_not_starve_other_routes(app, monkeypatch):
    """All slots busy and many uploads pending: health, info and the SPA still answer,
    and uploads past the waiter limit are refused with 503 at once."""
    monkeypatch.setattr(settings, "max_concurrent_imports", 2)
    monkeypatch.setattr(settings, "max_queued_requests", 3)
    monkeypatch.setattr(settings, "queue_timeout", 30.0)
    release, started = _hold_imports(app, monkeypatch)
    n = 45  # more than the 40 threads of the default pool

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30) as ac:
            uploads = [
                asyncio.create_task(ac.post("/api/files", files={"file": (f"u{i}.csv", b"a\n1\n")}))
                for i in range(n)
            ]
            await asyncio.sleep(0.5)
            t0 = time.monotonic()
            health = await ac.get("/api/health")
            info = await ac.get("/api/info")
            elapsed = time.monotonic() - t0
            refused = [t for t in uploads if t.done()]
            waiting = admission.imports.waiters
            release.set()
            results = await asyncio.gather(*uploads)
            return health, info, elapsed, refused, waiting, results

    health, info, elapsed, refused, waiting, results = asyncio.run(scenario())
    assert health.status_code == 200 and info.status_code == 200
    assert elapsed < 2.0
    assert len(started) <= 2 + 3  # the two running, then the three that waited
    assert waiting == 3
    assert len(refused) == n - 2 - 3
    assert all(t.result().status_code == 503 for t in refused)
    assert all(t.result().headers.get("retry-after") for t in refused)
    codes = sorted(r.status_code for r in results)
    assert codes.count(400) == 5 and codes.count(503) == n - 5
    assert admission.imports.used == 0 and admission.imports.waiters == 0


def test_waiting_upload_times_out_with_503(app, monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_imports", 1)
    monkeypatch.setattr(settings, "queue_timeout", 0.3)
    release, _ = _hold_imports(app, monkeypatch)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30) as ac:
            first = asyncio.create_task(ac.post("/api/files", files={"file": ("a.csv", b"a\n1\n")}))
            await asyncio.sleep(0.1)
            t0 = time.monotonic()
            second = await ac.post("/api/convert", files={"file": ("b.csv", b"a\n1\n")})
            waited = time.monotonic() - t0
            release.set()
            return await first, second, waited

    first, second, waited = asyncio.run(scenario())
    assert second.status_code == 503
    assert 0.25 < waited < 2.0
    assert first.status_code == 400
    assert admission.imports.used == 0


def test_imports_still_succeed_one_after_another(app, monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_imports", 1)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            return await asyncio.gather(
                *(ac.post("/api/files", files={"file": (f"s{i}.csv", b"a,b\n1,2\n3,4\n")}) for i in range(3))
            )

    results = asyncio.run(scenario())
    assert [r.status_code for r in results] == [200, 200, 200]
    assert admission.imports.used == 0
