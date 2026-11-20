"""One identifier policy: every element of an output is named ``urn:uuid:<uuid>`` (cdi/ids.py)."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.cdi.ids import IdMap, assign_ids
from ddicdi.models import DatasetMeta, Variable
from tests.test_api import _upload


@pytest.fixture()
def client(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    with TestClient(app) as c:
        yield c


def _ddicdi(client, fid, **body):
    r = client.post(f"/api/files/{fid}/generate", json={"max_rows": 2, **body})
    assert r.status_code == 200, r.text
    return json.loads(r.content)


def _cdif(client, fid, **body):
    r = client.post(f"/api/files/{fid}/generate", params={"format": "cdif"}, json={"max_rows": 0, **body})
    assert r.status_code == 200, r.text
    return json.loads(r.content)


def _nodes(obj, out=None):
    """Every node object (not value objects, not the context)."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        if "@value" not in obj and "@list" not in obj:
            out.append(obj)
        for k, v in obj.items():
            if k != "@context":
                _nodes(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _nodes(v, out)
    return out


def _strings(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k != "@context":
                yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)
    elif isinstance(obj, str):
        yield obj


def _meta(client, fid) -> DatasetMeta:
    return client.app.state.store.load(fid).meta


def _iri(client, fid, symbolic: str) -> str:
    return IdMap(_meta(client, fid)).iri(symbolic.lstrip("#"))


def _by_id(doc, iri):
    return next(x for x in doc["DDICDIModels"] if x["@id"] == iri)


@pytest.mark.parametrize("statistics", [False, True])
def test_every_ddicdi_node_has_a_uuid(client, statistics):
    fid = _upload(client).json()["file_id"]
    doc = _ddicdi(client, fid, include_statistics=statistics)
    nodes = _nodes(doc["DDICDIModels"])
    assert len(nodes) > len(doc["DDICDIModels"])  # the nested ones are counted too
    assert all(n.get("@id", "").startswith("urn:uuid:") for n in nodes), [n for n in nodes if "@id" not in n][:3]
    assert len({n["@id"] for n in nodes}) == len(nodes)  # all distinct
    assert not [s for s in _strings(doc) if s.startswith("#") and "-" in s]  # no symbolic reference left


def test_every_cdif_node_has_a_uuid(client):
    fid = _upload(client).json()["file_id"]
    doc = _cdif(client, fid, include_statistics=True)
    record = client.get(f"/api/files/{fid}/info").json()["record_id"]
    assert doc["@id"] == record
    nodes = [n for n in _nodes(doc) if set(n) != {"@id"}]  # not the bare references
    assert all(n.get("@id", "").startswith("urn:uuid:") for n in nodes), [n for n in nodes if "@id" not in n][:3]
    assert not any("#" in n["@id"] for n in nodes)


def test_ids_are_stable_and_shared_by_both_outputs(client):
    fid = _upload(client).json()["file_id"]
    first, second = _ddicdi(client, fid), _ddicdi(client, fid)
    assert first == second
    iv = _iri(client, fid, "#instanceVariable-ppltrst")
    assert _by_id(first, iv)["name"]["name"] == "ppltrst"
    cdif_var = next(v for v in _cdif(client, fid)["schema:variableMeasured"] if v["schema:name"] == "ppltrst")
    assert cdif_var["@id"] == iv


def test_a_rename_keeps_the_ids(client):
    fid = _upload(client).json()["file_id"]
    iv = _iri(client, fid, "#instanceVariable-ppltrst")
    codes = _iri(client, fid, "#substantiveCodeList-ppltrst")
    assert client.patch(f"/api/files/{fid}/variables/ppltrst", json={"new_name": "trust"}).status_code == 200
    doc = _ddicdi(client, fid)
    assert _by_id(doc, iv)["name"]["name"] == "trust"
    assert _by_id(doc, codes)["@type"] == "CodeList"


def test_two_uploads_of_one_file_do_not_share_ids(client):
    a, b = (_upload(client).json()["file_id"] for _ in range(2))
    ids_a = {n["@id"] for n in _nodes(_ddicdi(client, a)["DDICDIModels"])}
    ids_b = {n["@id"] for n in _nodes(_ddicdi(client, b)["DDICDIModels"])}
    assert not ids_a & ids_b


def test_readable_ids_keep_the_symbolic_ones(client, readable_ids):
    fid = _upload(client).json()["file_id"]
    doc = _ddicdi(client, fid)
    assert any(x["@id"] == "#instanceVariable-ppltrst" for x in doc["DDICDIModels"])
    assert not any("@id" in n for x in doc["DDICDIModels"] for n in _nodes(x)[1:])  # nested stay blank


@pytest.mark.parametrize("fmt", ["ddicdi", "cdif"])
def test_preview_names_the_elements_of_each_variable(client, fmt):
    fid = _upload(client).json()["file_id"]
    r = client.post(f"/api/files/{fid}/output", params={"format": fmt, "variable_ids": True}, json={"max_rows": 2})
    assert r.status_code == 200, r.text
    j = r.json()
    ppltrst = set(j["variable_ids"]["ppltrst"])
    assert _iri(client, fid, "#instanceVariable-ppltrst") in ppltrst
    assert not ppltrst & set(j["variable_ids"]["cntry"])
    # Without the flag the preview is the document itself.
    plain = client.post(f"/api/files/{fid}/output", params={"format": fmt}, json={"max_rows": 2}).json()
    assert plain == j["document"]


def test_old_workspace_gets_its_uuids_once(client):
    fid = _upload(client).json()["file_id"]
    store = client.app.state.store
    path = store.root / fid / "meta.json"
    raw = json.loads(path.read_text())
    raw.pop("doc_uuid")
    raw["store_id"] = "9d1c0f9e-1b7e-4c38-9d1a-3a6d1f6f0a11"  # its QLever id is kept
    for v in raw["variables"]:
        v.pop("uid")
    path.write_text(json.dumps(raw))
    first = store.load(fid).meta
    assert first.doc_uuid == "9d1c0f9e-1b7e-4c38-9d1a-3a6d1f6f0a11"
    assert [v.uid for v in store.load(fid).meta.variables] == [v.uid for v in first.variables]


def test_variable_names_with_dashes_and_prefixes():
    meta = DatasetMeta(variables=[Variable("a"), Variable("a-b")], number_rows=0, datafile="x.csv", file_format="csv")
    ids = IdMap(meta)
    keys = {v.name: v.uid for v in meta.variables}
    assert ids._stable_key("code-a-b-1") == (f"code-{keys['a-b']}-1", "a-b")
    assert ids._stable_key("code-a-1") == (f"code-{keys['a']}-1", "a")
    assert ids._stable_key("dataPoint-3-a-b") == (f"dataPoint-3-{keys['a-b']}", "a-b")
    assert ids._stable_key("componentPosition-3") == ("componentPosition-3", None)
    assert ids._stable_key("cdif-catalog-record") == ("cdif-catalog-record", None)
    assert ids.derive("x") == f"urn:uuid:{uuid.uuid5(uuid.UUID(meta.doc_uuid), 'x')}"


def test_text_that_looks_like_an_id_stays_text():
    meta = DatasetMeta(variables=[Variable("a")], number_rows=0, datafile="x.csv", file_format="csv")
    doc = {"@context": "x", "DDICDIModels": [
        {"@id": "#segment", "@type": "Segment"},
        {"@id": "#instanceVariable-a", "name": {"@type": "ObjectName", "name": "#segment"}, "uses": "#segment"},
    ]}
    out, _ = assign_ids(doc, meta)
    iv = out["DDICDIModels"][1]
    assert iv["name"]["name"] == "#segment" and iv["uses"] == out["DDICDIModels"][0]["@id"]
