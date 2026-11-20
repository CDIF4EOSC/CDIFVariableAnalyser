"""GitLab #13: statistics and edits run under admission control.
GitLab #14: a build reads no more rows than it was admitted for, and edits of one
upload take turns, so the stored row count stays right."""

import asyncio
import threading
import time

import httpx
import pytest

from ddicdi import stats
from ddicdi.api import admission, routes
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings


@pytest.fixture()
def app(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return app


def _csv(rows: int = 20, cols: int = 3) -> bytes:
    head = ",".join(f"v{i}" for i in range(cols))
    return (head + "\n" + "".join(",".join(str(r + c) for c in range(cols)) + "\n" for r in range(rows))).encode()


def test_statistics_are_admitted_and_health_stays_up(app, monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_heavy", 2)
    monkeypatch.setattr(settings, "max_queued_requests", 3)
    state = {"running": 0, "peak": 0}
    lock = threading.Lock()
    release = threading.Event()
    real = stats.summary_stats

    def slow(dataset, **kw):
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        release.wait(10)
        with lock:
            state["running"] -= 1
        return real(dataset, **kw)

    monkeypatch.setattr(stats, "summary_stats", slow)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            fids = []
            for i in range(4):
                r = await ac.post("/api/files", files={"file": (f"t{i}.csv", _csv())})
                fids.append(r.json()["file_id"])
            tasks = [
                asyncio.create_task(ac.get(f"/api/files/{fids[i % 4]}/statistics?refresh=true"))
                for i in range(30)
            ]
            await asyncio.sleep(1.0)
            running = state["running"]
            refused = [t.result().status_code for t in tasks if t.done()]
            t0 = time.monotonic()
            health = await ac.get("/api/health")
            elapsed = time.monotonic() - t0
            release.set()
            return running, refused, health, elapsed, await asyncio.gather(*tasks)

    running, refused, health, elapsed, results = asyncio.run(scenario())
    assert running == 2 and state["peak"] == 2
    assert refused and set(refused) == {503}
    assert health.status_code == 200 and elapsed < 2.0
    assert {r.status_code for r in results} <= {200, 503}
    assert admission.heavy.holders == 0 and admission.heavy.used == 0


def test_concurrent_row_appends_keep_the_count(app):
    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            fid = (await ac.post("/api/files", files={"file": ("t.csv", _csv(5))})).json()["file_id"]
            results = []
            for _ in range(5):  # batches within the per-upload queue limit
                results += await asyncio.gather(*(ac.post(f"/api/files/{fid}/rows", json={"values": {}}) for _ in range(6)))
            return fid, results

    fid, results = asyncio.run(scenario())
    ok = sum(r.status_code == 201 for r in results)
    assert ok == 30
    dataset = app.state.store.load(fid)
    with dataset.csv_path.open() as fh:
        records = sum(1 for _ in fh) - 1
    assert dataset.meta.number_rows == records == 5 + ok


def test_build_reads_only_the_admitted_rows(app, monkeypatch):
    """Rows appended to data.csv after the size check are not built."""
    from fastapi.testclient import TestClient

    client = TestClient(app)
    fid = client.post("/api/files", files={"file": ("t.csv", _csv(10))}).json()["file_id"]
    real = routes._render

    def render(dataset, req, fmt):
        with dataset.csv_path.open("a") as fh:  # rows the snapshot does not count
            fh.writelines("1,2,3\n" for _ in range(500))
        return real(dataset, req, fmt)

    monkeypatch.setattr(routes, "_render", render)
    r = client.post(f"/api/files/{fid}/output", json={"process_all_rows": True}, params={"format": "ddicdi"})
    assert r.status_code == 200, r.text
    assert r.text.count('"InstanceValue"') <= 10 * 3


def test_build_with_a_stale_row_count_reads_no_more(app, monkeypatch):
    from fastapi.testclient import TestClient

    client = TestClient(app)
    fid = client.post("/api/files", files={"file": ("t.csv", _csv(40))}).json()["file_id"]
    store = app.state.store
    dataset = store.load(fid)
    dataset.meta.number_rows = 4  # below the real count, as lost increments would leave it
    store.save_meta(fid, dataset.meta)
    r = client.post(f"/api/files/{fid}/output", json={"process_all_rows": True})
    assert r.status_code == 200
    assert r.text.count('"InstanceValue"') <= 4 * 3
