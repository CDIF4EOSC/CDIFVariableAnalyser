"""Save to / import from QLever (QLever-deployment/grilling-summary.md, Q2-Q9).

Most tests replace the store with an in-memory fake. The round-trip tests at the end
need a real QLever: set ``DDI_TEST_QLEVER_URL`` and ``DDI_TEST_QLEVER_ACCESS_TOKEN``
(a local one: ``qlever start`` with the deployment repo's Qleverfile); they skip otherwise.
"""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient
from rdflib import XSD, BNode, Graph, Literal
from rdflib.compare import graph_diff, isomorphic, to_isomorphic

from ddicdi import qlever
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings
from tests.test_api import _upload


# -- pure functions --------------------------------------------------------------------


@pytest.mark.parametrize("iri,ok", [
    ("urn:uuid:9d1c0f9e-1b7e-4c38-9d1a-3a6d1f6f0a11", True),
    ("https://doi.org/10.1234/x", True),
    ("not an iri", False),
    ("relative/path", False),
    ("https://e.org/a b", False),
    ('urn:x>"', False),
])
def test_absolute_iri(iri, ok):
    assert qlever.is_absolute_iri(iri) is ok


def test_restore_numeric_types():
    g = Graph()
    g.parse(data='<urn:a> <urn:p> "1"^^<http://www.w3.org/2001/XMLSchema#int> , '
                 '"1.5"^^<http://www.w3.org/2001/XMLSchema#decimal> , "x" .', format="turtle")
    restored = {o for o in qlever.restore_numeric_types(g).objects()}
    assert restored == {Literal("1", datatype=XSD.integer), Literal("1.5", datatype=XSD.double), Literal("x")}


# -- API with a fake store -------------------------------------------------------------


class FakeStore:
    def __init__(self):
        self.graphs: dict[str, Graph] = {}
        self.catalog: dict[str, qlever.CatalogEntry] = {}

    async def put_graph(self, name, graph):
        self.graphs[name] = graph

    async def write_catalog_entry(self, entry):
        self.catalog[entry.uuid] = entry

    async def construct_graph(self, name):
        return self.graphs.get(name, Graph())

    async def list_catalog(self):
        return [{"uuid": e.uuid, "graph": e.graph, "title": e.title, "dataset_iri": e.dataset_iri,
                 "source_file": e.source_file, "saved_at": e.saved_at, "saved_by": e.saved_by or None,
                 "triples": e.triples} for e in self.catalog.values()]


@pytest.fixture()
def fake(monkeypatch):
    store = FakeStore()
    for name in ("put_graph", "write_catalog_entry", "construct_graph", "list_catalog"):
        monkeypatch.setattr(qlever, name, getattr(store, name))
    monkeypatch.setattr(settings, "qlever_url", "http://qlever.invalid:7001")
    monkeypatch.setattr(settings, "qlever_access_token", "t")
    return store


@pytest.fixture()
def client(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    with TestClient(app) as c:
        yield c


def test_save_uses_the_document_uuid(client, fake):
    fid = _upload(client).json()["file_id"]
    record = client.get(f"/api/files/{fid}/info").json()["record_id"]
    assert record.startswith("urn:uuid:")

    r = client.post(f"/api/files/{fid}/qlever", json={})
    assert r.status_code == 200, r.text
    j = r.json()
    assert qlever.is_uuid(j["uuid"])
    assert j["graph"] == j["dataset_iri"] == record == f"urn:uuid:{j['uuid']}"

    graph = fake.graphs[j["graph"]]
    assert len(graph) == j["triples"]
    # No fragment or blank node: every subject and object node is a urn:uuid IRI.
    nodes = {n for t in graph for n in (t[0], t[2]) if not isinstance(n, Literal) and not str(n).startswith("http")}
    assert nodes and all(str(n).startswith("urn:uuid:") and "#" not in str(n) for n in nodes), sorted(nodes)[:5]
    assert not any(isinstance(n, BNode) for t in graph for n in t)
    assert fake.catalog[j["uuid"]].source_file == "ESS11-subset.sav"

    # A re-save replaces the same graph.
    again = client.post(f"/api/files/{fid}/qlever", json={"include_statistics": True}).json()
    assert again["uuid"] == j["uuid"] and len(fake.graphs) == 1
    assert again["triples"] > j["triples"]


def test_save_replaces_an_old_placeholder_record_iri(client, fake):
    fid = _upload(client).json()["file_id"]
    info = client.get(f"/api/files/{fid}/info").json()
    client.put(f"/api/files/{fid}/info", json={**info, "record_id": "urn:ddi-cdi:ESS11-subset"})
    j = client.post(f"/api/files/{fid}/qlever", json={}).json()
    assert j["dataset_iri"] == j["graph"] and j["info"]["record_id"] == j["graph"]


def test_save_uses_uuids_even_with_readable_ids(client, fake, readable_ids):
    fid = _upload(client).json()["file_id"]
    j = client.post(f"/api/files/{fid}/qlever", json={}).json()
    nodes = {str(n) for t in fake.graphs[j["graph"]] for n in (t[0], t[2]) if not isinstance(n, Literal)}
    assert all(n.startswith("urn:uuid:") and "#" not in n for n in nodes if not n.startswith("http"))


def test_a_record_iri_the_user_entered_is_kept(client, fake):
    fid = _upload(client).json()["file_id"]
    info = client.get(f"/api/files/{fid}/info").json()
    client.put(f"/api/files/{fid}/info", json={**info, "record_id": "https://example.org/records/42"})
    j = client.post(f"/api/files/{fid}/qlever").json()
    assert j["dataset_iri"] == "https://example.org/records/42"
    assert j["graph"] == f"urn:uuid:{j['uuid']}"


def test_an_invalid_record_iri_is_refused(client, fake):
    fid = _upload(client).json()["file_id"]
    info = client.get(f"/api/files/{fid}/info").json()
    client.put(f"/api/files/{fid}/info", json={**info, "record_id": "my record"})
    r = client.post(f"/api/files/{fid}/qlever", json={})
    assert r.status_code == 400 and "absolute IRI" in r.json()["detail"]
    assert not fake.graphs


def test_shacl_result_is_reported_not_enforced(client, fake, monkeypatch):
    monkeypatch.setattr(qlever, "shacl_check", lambda g: {"checked": True, "violations": ["bad"], "violation_count": 1, "warnings": 0})
    fid = _upload(client).json()["file_id"]
    r = client.post(f"/api/files/{fid}/qlever", json={})
    assert r.status_code == 200 and r.json()["shacl"]["violations"] == ["bad"]
    assert fake.graphs


def test_list_and_read_back(client, fake):
    fid = _upload(client).json()["file_id"]
    saved = client.post(f"/api/files/{fid}/qlever", json={}).json()
    docs = client.get("/api/qlever/documents").json()
    assert [d["uuid"] for d in docs] == [saved["uuid"]] and docs[0]["title"] == "ESS11-subset"

    r = client.get(f"/api/qlever/documents/{saved['uuid']}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/ld+json")
    assert "content-disposition" not in r.headers
    doc = r.json()
    assert any(n.get("@id") == saved["dataset_iri"] for n in doc["@graph"])

    r = client.get(f"/api/qlever/documents/{saved['uuid']}", params={"format": "turtle", "download": True})
    assert r.headers["content-disposition"] == f'attachment; filename="{saved["uuid"]}.ttl"'
    assert "@prefix schema: <http://schema.org/>" in r.text

    assert client.get(f"/api/qlever/documents/{qlever.new_uuid()}").status_code == 404
    assert client.get("/api/qlever/documents/not-a-uuid").status_code == 400


def test_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "qlever_url", "")
    fid = _upload(client).json()["file_id"]
    assert client.post(f"/api/files/{fid}/qlever", json={}).status_code == 503
    assert client.get("/api/qlever/documents").status_code == 503
    assert client.get("/api/info").json()["qlever"] is False


def test_unreachable_store_is_a_502(client, monkeypatch):
    monkeypatch.setattr(settings, "qlever_url", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "qlever_access_token", "t")
    r = client.get("/api/qlever/documents")
    assert r.status_code == 502 and "not reachable" in r.json()["detail"]


# -- round trip through a real QLever --------------------------------------------------

LIVE_URL = os.environ.get("DDI_TEST_QLEVER_URL")
live = pytest.mark.skipif(not LIVE_URL, reason="set DDI_TEST_QLEVER_URL (and _ACCESS_TOKEN) for a real QLever")


def _canonical(graph: Graph) -> Graph:
    """Doubles compared to 12 significant digits. QLever stores the full double (a FILTER
    on the exact value matches) but writes results with 12-13 significant digits, e.g.
    1.7653369903564453 comes back as 1.765336990356."""
    out = Graph()
    for s, p, o in graph:
        if isinstance(o, Literal) and o.datatype == XSD.double:
            o = Literal(format(float(o), ".12g"), datatype=XSD.double)
        out.add((s, p, o))
    return out


@pytest.fixture()
def live_store(monkeypatch):
    monkeypatch.setattr(settings, "qlever_url", LIVE_URL)
    monkeypatch.setattr(settings, "qlever_access_token", os.environ.get("DDI_TEST_QLEVER_ACCESS_TOKEN", ""))
    saved: list[str] = []
    yield saved
    import asyncio

    for doc_uuid in saved:  # leave the store as it was
        asyncio.run(qlever.update(
            f"DROP SILENT GRAPH <{qlever.graph_iri(doc_uuid)}> ;\n"
            f"DELETE WHERE {{ GRAPH <{qlever.CATALOG}> {{ <{qlever.entry_iri(doc_uuid)}> ?p ?o }} }} ;\n"
            f"DELETE DATA {{ GRAPH <{qlever.CATALOG}> {{ <{qlever.CATALOG}> <{qlever.DCAT.record}> <{qlever.entry_iri(doc_uuid)}> }} }}"
        ))


@live
@pytest.mark.parametrize("statistics", [False, True])
def test_round_trip_is_isomorphic(client, live_store, monkeypatch, statistics):
    sent: dict[str, Graph] = {}
    put = qlever.put_graph

    async def spy(name, graph):
        sent[name] = graph
        await put(name, graph)

    monkeypatch.setattr(qlever, "put_graph", spy)
    fid = _upload(client).json()["file_id"]
    r = client.post(f"/api/files/{fid}/qlever", json={"include_statistics": statistics})
    assert r.status_code == 200, r.text
    saved = r.json()
    live_store.append(saved["uuid"])

    import asyncio

    back = qlever.restore_numeric_types(asyncio.run(qlever.construct_graph(saved["graph"])))
    original = sent[saved["graph"]]
    assert len(back) == len(original) == saved["triples"]
    a, b = _canonical(original), _canonical(back)
    if not isomorphic(a, b):
        _, only_sent, only_back = graph_diff(to_isomorphic(a), to_isomorphic(b))
        pytest.fail(f"not isomorphic; sent only: {sorted(only_sent)[:5]}; stored only: {sorted(only_back)[:5]}")

    assert saved["uuid"] in [d["uuid"] for d in client.get("/api/qlever/documents").json()]
    # The JSON-LD the editor shows parses back to the same graph.
    shown = Graph().parse(data=client.get(f"/api/qlever/documents/{saved['uuid']}").text, format="json-ld")
    assert isomorphic(_canonical(shown), b)


@live
def test_resave_replaces_the_graph(client, live_store):
    fid = _upload(client).json()["file_id"]
    first = client.post(f"/api/files/{fid}/qlever", json={"include_statistics": True}).json()
    live_store.append(first["uuid"])
    second = client.post(f"/api/files/{fid}/qlever", json={}).json()
    assert second["uuid"] == first["uuid"] and second["triples"] < first["triples"]
    import asyncio

    assert len(asyncio.run(qlever.construct_graph(first["graph"]))) == second["triples"]
    entries = [d for d in client.get("/api/qlever/documents").json() if d["uuid"] == first["uuid"]]
    assert len(entries) == 1 and entries[0]["triples"] == second["triples"]


def test_check_cdif_without_saving(client, monkeypatch):
    monkeypatch.setattr(settings, "qlever_url", "")  # the check needs no QLever
    fid = _upload(client).json()["file_id"]
    r = client.post(f"/api/files/{fid}/cdif/check", json={"include_statistics": True})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["checked"] and j["shapes"] == "CDIF-Complete-Shapes.ttl"  # the vendored shapes
    assert j["violation_count"] == 0 and j["violations"] == []
    assert j["warnings"] >= len(j["warning_messages"]) > 0
    assert any("creator" in m for m in j["warning_messages"])  # nothing filled in on the Dataset tab yet


def test_check_reports_missing_shapes(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "cdif_shacl_shapes", tmp_path / "none.ttl")
    fid = _upload(client).json()["file_id"]
    j = client.post(f"/api/files/{fid}/cdif/check", json={}).json()
    assert j["checked"] is False and "none.ttl" in j["reason"]


def test_check_reports_every_missing_required_field(client):
    fid = _upload(client).json()["file_id"]
    j = client.post(f"/api/files/{fid}/cdif/check", json={}).json()
    assert [m.split(" is missing")[0] for m in j["missing_required"]] == ["Licence"]  # import fills title and dates
    info = client.get(f"/api/files/{fid}/info").json()
    client.put(f"/api/files/{fid}/info", json={**info, "title": "", "date_modified": ""})
    j = client.post(f"/api/files/{fid}/cdif/check", json={}).json()
    assert [m.split(" is missing")[0] for m in j["missing_required"]] == ["Title", "Licence", "Date modified"]
    assert "'ESS11-subset' is used instead" in j["missing_required"][0]
    client.put(f"/api/files/{fid}/info", json={
        **info, "license": "https://creativecommons.org/licenses/by/4.0/"})
    assert client.post(f"/api/files/{fid}/cdif/check", json={}).json()["missing_required"] == []
