"""Security #8: concurrent generate/output/convert builds share one memory budget."""

import asyncio
import threading
import time

import httpx
import pytest

from ddicdi.api import admission, routes
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings

ROWS, COLS = 200, 5  # 1000 cells at full size


@pytest.fixture()
def app(tmp_path, qsv, monkeypatch):
    monkeypatch.setattr(settings, "max_output_cells", 1500)
    monkeypatch.setattr(settings, "max_concurrent_builds", 4)
    monkeypatch.setattr(settings, "max_queued_requests", 2)
    monkeypatch.setattr(settings, "queue_timeout", 30.0)
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return app


def _csv() -> bytes:
    head = ",".join(f"v{i}" for i in range(COLS))
    return (head + "\n" + "".join(",".join(str(r + c) for c in range(COLS)) + "\n" for r in range(ROWS))).encode()


def _instrument(monkeypatch):
    """Count builds running at once; each build blocks until released."""
    state = {"running": 0, "peak": 0}
    lock = threading.Lock()
    release = threading.Event()
    real = routes._render

    def render(dataset, req, fmt):
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        try:
            release.wait(10)
            return real(dataset, req, fmt)
        finally:
            with lock:
                state["running"] -= 1

    monkeypatch.setattr(routes, "_render", render)
    return state, release


@pytest.mark.parametrize("endpoint", ["output", "generate"])
def test_parallel_full_size_builds_run_one_at_a_time(app, monkeypatch, endpoint):
    """Each request fits the cap alone; together they must not run at once."""
    state, release = _instrument(monkeypatch)
    n = 6

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            r = await ac.post("/api/files", files={"file": ("w.csv", _csv())})
            fid = r.json()["file_id"]
            tasks = [
                asyncio.create_task(ac.post(f"/api/files/{fid}/{endpoint}", json={"process_all_rows": True}))
                for _ in range(n)
            ]
            await asyncio.sleep(0.5)
            running = state["running"]
            refused = [t.result().status_code for t in tasks if t.done()]
            t0 = time.monotonic()
            health = await ac.get("/api/health")
            elapsed = time.monotonic() - t0
            release.set()
            return running, refused, health, elapsed, await asyncio.gather(*tasks)

    running, refused, health, elapsed, results = asyncio.run(scenario())
    assert running == 1  # 1000 cells + 20 per-variable units: a second does not fit 1500
    assert refused == [503] * (n - 1 - 2)  # one runs, two wait, the rest are refused at once
    assert health.status_code == 200 and elapsed < 2.0
    codes = sorted(r.status_code for r in results)
    assert codes == [200] * 3 + [503] * (n - 3)
    assert state["peak"] == 1
    assert admission.builds.used == 0 and admission.builds.holders == 0


def test_small_builds_still_run_side_by_side(app, monkeypatch):
    state, release = _instrument(monkeypatch)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            r = await ac.post("/api/files", files={"file": ("w.csv", _csv())})
            fid = r.json()["file_id"]
            tasks = [
                asyncio.create_task(ac.post(f"/api/files/{fid}/output", json={"max_rows": 5}))
                for _ in range(6)
            ]
            await asyncio.sleep(0.5)
            running = state["running"]
            release.set()
            return running, await asyncio.gather(*tasks)

    running, results = asyncio.run(scenario())
    assert running == 4  # max_concurrent_builds, although 4 x 45 cells is far below the budget
    assert [r.status_code for r in results] == [200] * 6


def test_oversized_request_is_413_without_queueing(app, monkeypatch):
    monkeypatch.setattr(settings, "max_output_cells", 500)
    _instrument(monkeypatch)[1].set()

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            r = await ac.post("/api/files", files={"file": ("w.csv", _csv())})
            fid = r.json()["file_id"]
            return await ac.post(f"/api/files/{fid}/output", json={"process_all_rows": True})

    assert asyncio.run(scenario()).status_code == 413
    assert admission.builds.used == 0


def test_convert_holds_the_build_budget(app, monkeypatch):
    state, release = _instrument(monkeypatch)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            tasks = [
                asyncio.create_task(
                    ac.post("/api/convert", files={"file": (f"c{i}.csv", _csv())}, data={"process_all_rows": "true"})
                )
                for i in range(3)
            ]
            deadline = time.monotonic() + 10
            while state["running"] == 0 and time.monotonic() < deadline:
                await asyncio.sleep(0.05)
            await asyncio.sleep(0.5)
            running = state["running"]
            release.set()
            return running, await asyncio.gather(*tasks)

    running, results = asyncio.run(scenario())
    assert running == 1
    assert [r.status_code for r in results] == [200, 200, 200]
