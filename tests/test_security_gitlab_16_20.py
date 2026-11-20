"""GitLab #16, #18, #19 and #20."""

import asyncio
import json
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from rdflib import Graph

from ddicdi import editing, enrich, qlever
from ddicdi.api import admission
from ddicdi.api.main import create_app
from ddicdi.api.store import StorageFull, UploadStore
from ddicdi.config import settings
from ddicdi.models import DatasetMeta, MissingRange, Variable


@pytest.fixture()
def app(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return app


@pytest.fixture()
def client(app):
    return TestClient(app)


def _upload(client, body: bytes) -> str:
    r = client.post("/api/files", files={"file": ("t.csv", body)})
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


# -- #16: edits are measured in bytes ------------------------------------------------------


def _multibyte_csv(rows: int = 200) -> bytes:
    return ("a,b\n" + "".join(f"{i},{'𝄞' * 20}\n" for i in range(rows))).encode("utf-8")


def test_copy_of_multibyte_column_is_refused_when_the_work_dir_is_full(app, client, monkeypatch):
    fid = _upload(client, _multibyte_csv())
    store = app.state.store
    monkeypatch.setattr(settings, "work_dir_max_bytes", editing.work_dir_usage(store.root))  # full now
    csv_path = store.load(fid).csv_path
    before = csv_path.stat().st_size
    r = client.post(f"/api/files/{fid}/variables", json={"name": "c", "fill": "copy", "fill_value": "b"})
    assert r.status_code == 400 and "storage limit" in r.json()["detail"]
    assert csv_path.stat().st_size == before
    # same-size and shrinking edits still work on a full work dir
    assert client.patch(f"/api/files/{fid}/rows/0", json={"values": {"a": "9"}}).status_code == 200
    assert client.delete(f"/api/files/{fid}/variables/b").status_code == 200


def test_rewrite_limit_counts_bytes_not_characters(app, client, monkeypatch):
    fid = _upload(client, _multibyte_csv(50))
    dataset = app.state.store.load(fid)
    size = dataset.csv_path.stat().st_size
    # Room for the copy in characters, not in bytes (each 𝄞 is 4 bytes, 1 character).
    monkeypatch.setattr(settings, "edit_max_csv_bytes", size + 50 * 25)
    with pytest.raises(editing.EditError, match="storage limit"):
        editing.add_variable(dataset, editing.NewVariable(name="c", fill="copy", fill_value="b"))


def test_append_counts_the_exact_bytes(app, client, monkeypatch):
    fid = _upload(client, b"a,b\n1,2\n")
    dataset = app.state.store.load(fid)
    size = dataset.csv_path.stat().st_size
    line = '"x""y",𝄞\n'.encode("utf-8")
    monkeypatch.setattr(settings, "edit_max_csv_bytes", size + len(line) - 1)
    with pytest.raises(editing.EditError):
        editing.append_row(dataset, {"a": 'x"y', "b": "𝄞"})
    monkeypatch.setattr(settings, "edit_max_csv_bytes", size + len(line))
    editing.append_row(dataset, {"a": 'x"y', "b": "𝄞"})
    assert dataset.csv_path.stat().st_size == size + len(line)


# -- #19: every enrichment field is bounded --------------------------------------------------


def test_enrichment_item_has_a_fixed_maximum_size():
    var = Variable(
        name="v",
        format="F" * 10_000,
        storage_type="t" * 10_000,
        missing_ranges=[MissingRange("m" * 5000, "m" * 5000) for _ in range(500)],
    )
    item = enrich.variable_input(var)
    assert len(item["variable_format"]) <= enrich.MAX_FORMAT_CHARS
    assert len(item["variable_datatype"]) <= enrich.MAX_FORMAT_CHARS
    assert len(item["variable_missing_values"]) <= enrich.MAX_MISSING_VALUES
    assert all(len(m) <= enrich.MAX_MISSING_VALUE_CHARS for m in item["variable_missing_values"])


def test_edit_api_refuses_oversized_format_type_and_missing(client):
    fid = _upload(client, b"a,b\n1,x\n")
    long = "x" * (settings.max_format_chars + 1)
    assert client.patch(f"/api/files/{fid}/variables/b", json={"format": long}).status_code == 400
    assert client.patch(f"/api/files/{fid}/variables/b", json={"type": long}).status_code == 400
    assert client.post(f"/api/files/{fid}/variables", json={"name": "c", "format": long}).status_code == 400
    missing = [{"lo": "m" * (settings.max_code_chars + 1)}]
    assert client.patch(f"/api/files/{fid}/variables/b", json={"missing": missing}).status_code == 400


# -- #20: opened workspaces count against the quota ----------------------------------------------


def _meta(n: int = 3) -> DatasetMeta:
    return DatasetMeta(variables=[Variable(name=f"v{i}") for i in range(n)], number_rows=0, datafile="x", file_format="csv")


def test_metadata_workspace_respects_the_quota(tmp_path, monkeypatch):
    store = UploadStore(tmp_path / "u", ttl_seconds=3600)
    monkeypatch.setattr(settings, "work_dir_max_bytes", 2000)
    opened = 0
    with pytest.raises(StorageFull):
        for _ in range(100):
            store.create_from_meta(_meta())
            opened += 1
    assert 0 < opened < 100
    assert editing.work_dir_usage(store.root) <= 2000


def test_oversized_metadata_is_refused_and_leaves_nothing(tmp_path, monkeypatch):
    from ddicdi.api.store import MetadataTooLarge

    store = UploadStore(tmp_path / "u", ttl_seconds=3600)
    monkeypatch.setattr(settings, "max_meta_bytes", 100)
    with pytest.raises(MetadataTooLarge):
        store.create_from_meta(_meta(20))
    assert list(store.root.iterdir()) == []


# -- #18: reading a saved document is bounded and off the event loop -----------------------------


def _nt(n: int) -> bytes:
    return "".join(f"<urn:s{i}> <urn:p> \"{i}\" .\n" for i in range(n)).encode()


@pytest.fixture()
def qlever_http(monkeypatch):
    """QLever answering every CONSTRUCT with ``state['body']``."""
    state = {"body": _nt(10), "delay": 0.0}
    monkeypatch.setattr(settings, "qlever_url", "http://qlever.invalid:7001")
    monkeypatch.setattr(settings, "qlever_access_token", "t")

    async def handler(request):
        await asyncio.sleep(state["delay"])
        return httpx.Response(200, content=state["body"], headers={"Content-Type": "application/n-triples"})

    monkeypatch.setattr(qlever, "_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return state


def test_construct_graph_is_capped_in_bytes(qlever_http, monkeypatch):
    monkeypatch.setattr(settings, "qlever_max_document_bytes", 100)
    with pytest.raises(qlever.QleverError) as err:
        asyncio.run(qlever.construct_graph("urn:uuid:x"))
    assert err.value.status_code == 413
    monkeypatch.setattr(settings, "qlever_max_document_bytes", 1 << 20)
    assert len(asyncio.run(qlever.construct_graph("urn:uuid:x"))) == 10


def test_construct_graph_parses_off_the_event_loop(qlever_http, monkeypatch):
    threads = []
    real = Graph.parse

    def spy(self, *a, **kw):
        threads.append(threading.current_thread() is threading.main_thread())
        return real(self, *a, **kw)

    monkeypatch.setattr(Graph, "parse", spy)
    asyncio.run(qlever.construct_graph("urn:uuid:x"))
    assert threads == [False]


def test_document_reads_are_admitted(app, qlever_http, monkeypatch):
    monkeypatch.setattr(settings, "max_concurrent_qlever_reads", 1)
    monkeypatch.setattr(settings, "max_queued_requests", 1)
    qlever_http["delay"] = 1.0
    uuid = "12345678-1234-1234-1234-123456789abc"

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", timeout=60) as ac:
            tasks = [asyncio.create_task(ac.get(f"/api/qlever/documents/{uuid}")) for _ in range(5)]
            await asyncio.sleep(0.3)
            refused = [t.result().status_code for t in tasks if t.done()]
            t0 = time.monotonic()
            health = await ac.get("/api/health")
            elapsed = time.monotonic() - t0
            return refused, health, elapsed, await asyncio.gather(*tasks)

    refused, health, elapsed, results = asyncio.run(scenario())
    assert refused == [503, 503, 503]  # one reads, one waits
    assert health.status_code == 200 and elapsed < 1.0
    assert sorted(r.status_code for r in results) == [200, 200, 503, 503, 503]
    assert admission.qlever_reads.holders == 0
    assert json.loads(results[[r.status_code for r in results].index(200)].content)
