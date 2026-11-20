"""GitLab #10: CDIF check and QLever save hold the build budget through the RDF and
SHACL work; validations are few, bounded in size and time, and off the event loop."""

import asyncio
import threading
import time

import httpx
import pytest
from rdflib import Graph

from ddicdi import qlever
from ddicdi.api import admission, routes
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings


@pytest.fixture()
def app(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return app


def _graph(n: int) -> Graph:
    g = Graph()
    g.parse(data="".join(f"<urn:s{i}> <urn:p> <urn:o{i}> .\n" for i in range(n)), format="nt")
    return g


def test_large_graph_is_not_checked(monkeypatch):
    monkeypatch.setattr(settings, "shacl_max_triples", 10)
    result = qlever.shacl_check(_graph(11))
    assert result["checked"] is False and "not checked" in result["reason"]


def test_validation_over_its_deadline_is_stopped(monkeypatch):
    monkeypatch.setattr(settings, "shacl_timeout", 0.001)
    t0 = time.monotonic()
    result = qlever.shacl_check(_graph(5_000))
    assert result["checked"] is False and "stopped" in result["reason"]
    assert time.monotonic() - t0 < 30
    monkeypatch.setattr(settings, "shacl_timeout", 120.0)
    assert qlever.shacl_check(_graph(3))["checked"] is True  # a new pool after the kill


def test_checks_hold_the_build_budget_and_run_one_validation_at_a_time(app, monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_validations", 1)
    monkeypatch.setattr(settings, "max_queued_requests", 2)
    state = {"running": 0, "peak": 0, "budget": []}
    lock = threading.Lock()
    release = threading.Event()

    def slow_check(graph):
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
            state["budget"].append(admission.builds.used)
        release.wait(10)
        with lock:
            state["running"] -= 1
        return {"checked": True, "violations": [], "warnings": 0}

    monkeypatch.setattr(qlever, "shacl_check", slow_check)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            r = await ac.post("/api/files", files={"file": ("t.csv", b"a,b\n1,2\n")})
            fid = r.json()["file_id"]
            tasks = [asyncio.create_task(ac.post(f"/api/files/{fid}/cdif/check")) for _ in range(6)]
            await asyncio.sleep(1.0)
            running = state["running"]
            refused = [t.result().status_code for t in tasks if t.done()]
            t0 = time.monotonic()
            health = await ac.get("/api/health")
            elapsed = time.monotonic() - t0
            release.set()
            return running, refused, health, elapsed, await asyncio.gather(*tasks)

    running, refused, health, elapsed, results = asyncio.run(scenario())
    assert running == 1 and state["peak"] == 1
    assert refused and set(refused) == {503}  # past the validation queue
    assert all(used > 0 for used in state["budget"])  # the build slot is held during SHACL
    assert health.status_code == 200 and elapsed < 2.0
    assert admission.builds.used == 0 and admission.validations.holders == 0


def test_put_graph_serialises_off_the_event_loop(monkeypatch):
    threads = []
    real = Graph.serialize

    def spy(self, *a, **kw):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(self, *a, **kw)

    async def fake_send(*a, **kw):
        return None

    monkeypatch.setattr(Graph, "serialize", spy)
    monkeypatch.setattr(qlever, "_send", fake_send)
    monkeypatch.setattr(settings, "qlever_access_token", "t")
    asyncio.run(qlever.put_graph("urn:g", _graph(3)))
    assert threads == [False]


def test_cdif_cost_includes_the_rdf_factor(app, monkeypatch, qsv):
    seen = []
    real = admission.builds.slot

    def slot(cost=1):
        seen.append(cost)
        return real(cost)

    monkeypatch.setattr(admission.builds, "slot", slot)
    monkeypatch.setattr(qlever, "shacl_check", lambda g: {"checked": False, "reason": "x", "violations": [], "warnings": 0})
    from fastapi.testclient import TestClient

    client = TestClient(app)
    fid = client.post("/api/files", files={"file": ("t.csv", b"a,b\n1,2\n")}).json()["file_id"]
    assert client.post(f"/api/files/{fid}/cdif/check").status_code == 200
    dataset = app.state.store.load(fid)
    plain = routes._build_cost(dataset, routes.OutputRequest(max_rows=0), "cdif")
    assert seen == [plain * admission.RDF_FACTOR]
