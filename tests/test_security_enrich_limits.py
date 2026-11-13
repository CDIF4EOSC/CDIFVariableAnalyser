"""Security #11: one enrich request makes bounded n8n work, and few run at once."""

import asyncio
import io
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from ddicdi import enrich
from ddicdi.api import admission
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings
from ddicdi.models import Variable


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(settings, "n8n_bearer_key", "Bearer test")
    for kind in ("unit", "concept", "role", "function", "measure"):
        monkeypatch.setattr(settings, f"n8n_{kind}_url", f"https://n8n.test/{kind}")
    monkeypatch.setattr(enrich, "BACKOFF", 0.0)


def _vars(n: int, **kw) -> list[Variable]:
    return [Variable(name=f"v{i}", **kw) for i in range(n)]


def test_concurrency_is_shared_across_kinds(configured, monkeypatch):
    monkeypatch.setattr(settings, "n8n_concurrency", 3)
    state = {"now": 0, "peak": 0, "calls": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        state["now"] += 1
        state["calls"] += 1
        state["peak"] = max(state["peak"], state["now"])
        await asyncio.sleep(0.01)
        state["now"] -= 1
        names = [v["variable_name"] for v in json.loads(request.content)["variables"]]
        return httpx.Response(200, json={"results": [{"variable_name": n, "status": "ok"} for n in names]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(enrich.enrich(_vars(100), client=client))
    assert state["peak"] <= 3
    # 100 concept calls + 5 batches of 20 for each of the four batched kinds
    assert state["calls"] == 100 + 4 * 5


def test_mismatched_concept_results_use_one_attempt_budget(configured):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"results": [{"variable_name": "someone-else"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = asyncio.run(enrich.enrich(_vars(1), ["concept"], client=client))
    assert calls["n"] == enrich.ATTEMPTS  # not ATTEMPTS x ATTEMPTS
    assert res.errors and res.errors[0]["name"] == "v0"


def test_transport_errors_and_mismatches_share_the_budget(configured):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] % 2:
            return httpx.Response(502)
        return httpx.Response(200, json={"results": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(enrich.enrich(_vars(1), ["concept"], client=client))
    assert calls["n"] == enrich.ATTEMPTS


def test_long_text_is_cut_and_long_names_are_not_sent(configured):
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)["variables"]
        sent.extend(body)
        return httpx.Response(200, json={"results": [{"variable_name": v["variable_name"]} for v in body]})

    long_name = "n" * (enrich.MAX_NAME_CHARS + 1)
    variables = [
        Variable(name="ok", label="L" * 10_000, value_labels={"1": "V" * 10_000, "2" * 1000: "x"}),
        Variable(name=long_name),
    ]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = asyncio.run(enrich.enrich(variables, ["unit", "concept"], client=client))
    assert {v["variable_name"] for v in sent} == {"ok"}
    for v in sent:
        assert len(v["variable_label"]) == enrich.MAX_LABEL_CHARS
        for vl in v["variable_value_labels"]:
            assert len(vl["label"]) <= enrich.MAX_VALUE_LABEL_CHARS
            assert len(vl["value"]) <= enrich.MAX_VALUE_LABEL_CHARS
    assert sorted(e["kind"] for e in res.errors if e["name"] == long_name) == ["concept", "unit"]


def test_deadline_cancels_outstanding_calls(configured, monkeypatch):
    monkeypatch.setattr(settings, "enrich_deadline", 0.3)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(30)
        return httpx.Response(200, json={"results": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    t0 = time.monotonic()
    with pytest.raises(enrich.EnrichError, match="longer than"):
        asyncio.run(enrich.enrich(_vars(3), client=client))
    assert time.monotonic() - t0 < 5


# -- route ------------------------------------------------------------------------------


@pytest.fixture()
def app(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return app


def _wide_csv(cols: int) -> bytes:
    return (",".join(f"c{i}" for i in range(cols)) + "\n" + ",".join("1" for _ in range(cols)) + "\n").encode()


def test_too_many_variables_is_refused_without_calling_n8n(app, configured, monkeypatch):
    monkeypatch.setattr(settings, "max_enrich_variables", 10)
    called = []

    async def fake(*args, **kwargs):
        called.append(1)
        return enrich.EnrichResult()

    monkeypatch.setattr(enrich, "enrich", fake)
    with TestClient(app) as c:
        fid = c.post("/api/files", files={"file": ("w.csv", io.BytesIO(_wide_csv(11)))}).json()["file_id"]
        r = c.post(f"/api/files/{fid}/enrich", json={})
        assert r.status_code == 413 and "limit is 10" in r.text
        r = c.post(f"/api/files/{fid}/enrich", json={"variables": [f"c{i}" for i in range(11)]})
        assert r.status_code == 413
        assert called == []
        r = c.post(f"/api/files/{fid}/enrich", json={"variables": [f"c{i}" for i in range(10)]})
        assert r.status_code == 200, r.text
    assert called == [1]


def test_concurrent_enrich_requests_are_bounded(app, configured, monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_enrich", 2)
    monkeypatch.setattr(settings, "max_queued_requests", 1)
    monkeypatch.setattr(settings, "queue_timeout", 30.0)
    state = {"now": 0, "peak": 0}
    release = asyncio.Event

    async def scenario():
        gate = release()

        async def fake(variables, kinds, *, client=None):
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            await gate.wait()
            state["now"] -= 1
            return enrich.EnrichResult()

        monkeypatch.setattr(enrich, "enrich", fake)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=30) as ac:
            fid = (await ac.post("/api/files", files={"file": ("w.csv", _wide_csv(3))})).json()["file_id"]
            tasks = [asyncio.create_task(ac.post(f"/api/files/{fid}/enrich", json={})) for _ in range(6)]
            await asyncio.sleep(0.3)
            refused = [t.result().status_code for t in tasks if t.done()]
            gate.set()
            return refused, await asyncio.gather(*tasks)

    refused, results = asyncio.run(scenario())
    assert state["peak"] == 2
    assert refused == [503, 503, 503]  # two run, one waits, three refused at once
    assert sorted(r.status_code for r in results) == [200, 200, 200, 503, 503, 503]
    assert admission.enrichments.used == 0


def test_deadline_is_a_504(app, configured, monkeypatch):
    async def slow(*args, **kwargs):
        raise enrich.EnrichError("AI enrichment took longer than 1s and was stopped")

    monkeypatch.setattr(enrich, "enrich", slow)
    with TestClient(app) as c:
        fid = c.post("/api/files", files={"file": ("w.csv", io.BytesIO(_wide_csv(3)))}).json()["file_id"]
        r = c.post(f"/api/files/{fid}/enrich", json={})
    assert r.status_code == 504
