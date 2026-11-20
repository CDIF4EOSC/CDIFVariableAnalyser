"""GitLab #15: an enrich request is validated in linear time, refused by its own length
before any per-item work, and builds its payloads off the event loop."""

import asyncio
import json
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from ddicdi import enrich
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings
from ddicdi.models import Variable


@pytest.fixture()
def client(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return TestClient(app)


def test_long_variables_list_is_refused_before_it_is_scanned(client, monkeypatch):
    monkeypatch.setattr(settings, "max_enrich_variables", 10)
    fid = client.post("/api/files", files={"file": ("t.csv", b"a,b\n1,2\n")}).json()["file_id"]
    loads = []
    monkeypatch.setattr("ddicdi.api.routes._load", lambda *a: loads.append(1))
    r = client.post(f"/api/files/{fid}/enrich", json={"variables": ["a"] * 11, "kinds": ["unit"]})
    assert r.status_code == 413
    assert loads == []  # not even the upload was loaded


def test_repeated_names_within_the_limit_are_fine(client, monkeypatch):
    fid = client.post("/api/files", files={"file": ("t.csv", b"a,b\n1,2\n")}).json()["file_id"]
    r = client.post(f"/api/files/{fid}/enrich", json={"variables": ["a", "a", "zz"], "kinds": ["unit"]})
    assert r.status_code == 400 and r.json()["detail"] == "Unknown variables: ['zz']"


def test_payloads_are_built_once_and_off_the_event_loop(monkeypatch):
    monkeypatch.setattr(settings, "n8n_bearer_key", "Bearer test")
    for kind in ("unit", "concept", "role", "function", "measure"):
        monkeypatch.setattr(settings, f"n8n_{kind}_url", f"https://n8n.test/{kind}")
    calls = []
    real = enrich.variable_input

    def spy(var):
        calls.append(threading.current_thread() is threading.main_thread())
        return real(var)

    monkeypatch.setattr(enrich, "variable_input", spy)

    async def handler(request: httpx.Request) -> httpx.Response:
        names = [v["variable_name"] for v in json.loads(request.content)["variables"]]
        return httpx.Response(200, json={"results": [{"variable_name": n, "status": "ok"} for n in names]})

    variables = [Variable(name=f"v{i}", value_labels={str(c): "x" for c in range(50)}) for i in range(5)]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    asyncio.run(enrich.enrich(variables, client=client))
    assert calls == [False] * 5  # once per variable, never on the loop's thread
