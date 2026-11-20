"""Open from QLever (step a): a saved document back in the editor, and what the round trip loses.

The store is the in-memory fake of ``test_qlever``; ``cdif/reverse.py`` lists the losses
these tests pin down.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from rdflib import Literal
from rdflib.compare import graph_diff, isomorphic, to_isomorphic

from ddicdi import qlever
from tests.test_api import _upload
from tests.test_cdif import INFO
from tests.test_qlever import client, fake, live, live_store  # noqa: F401  (fixtures)


def _saved(client, **roles):
    fid = _upload(client).json()["file_id"]
    info = client.get(f"/api/files/{fid}/info").json()
    client.put(f"/api/files/{fid}/info", json={**info, **INFO, "record_id": info["record_id"]})
    client.put(f"/api/files/{fid}/roles", json={"roles": roles or {"idno": "identifier", "cntry": "attribute"}})
    saved = client.post(f"/api/files/{fid}/qlever", json={}).json()
    return fid, saved


def _open(client, doc_uuid):
    r = client.post(f"/api/qlever/documents/{doc_uuid}/open")
    assert r.status_code == 200, r.text
    return r.json()


def _meta(client, fid):
    return client.app.state.store.load(fid).meta


def _cdif_graph(client, fid):
    r = client.post(f"/api/files/{fid}/generate", params={"format": "cdif"}, json={"max_rows": 0})
    return qlever.cdif_graph(json.loads(r.content))


def test_open_gives_a_metadata_only_session(client, fake):
    fid, saved = _saved(client)
    j = _open(client, saved["uuid"])
    assert j["file_id"] != fid
    assert j["opened_from"] == saved["graph"] and j["source_rows"] == 2420
    assert j["number_rows"] == 0 and j["filename"] == "ESS11-subset.sav" and j["file_format"] == "spss"
    assert j["info"]["title"] == INFO["title"] and j["info"]["record_id"] == saved["dataset_iri"]
    assert client.get(f"/api/files/{j['file_id']}/preview", params={"rows": 5}).json()["rows"] == []


def test_variables_and_roles_survive(client, fake):
    fid, saved = _saved(client)
    before, after = _meta(client, fid), _meta(client, _open(client, saved["uuid"])["file_id"])
    assert [dataclasses.asdict(v) for v in after.variables] == [dataclasses.asdict(v) for v in before.variables]
    assert {r: set(getattr(after.roles, r)) for r in ("identifier", "attribute", "measure")} == {
        r: set(getattr(before.roles, r)) for r in ("identifier", "attribute", "measure")}
    assert after.doc_uuid == before.doc_uuid


def test_the_description_loses_only_what_rdf_cannot_order(client, fake):
    fid, saved = _saved(client)
    before = dataclasses.asdict(_meta(client, fid).info)
    after = dataclasses.asdict(_meta(client, _open(client, saved["uuid"])["file_id"]).info)
    changed = {k for k in before if before[k] != after[k]}
    # keywords and places: sets in RDF (sorted, blanks dropped); contributors: a set
    # too; creators: a bare ORCID / ROR comes back as its IRI.
    assert changed == {"keywords", "spatial", "contributors", "creators"}
    assert after["keywords"] == sorted(k for k in before["keywords"] if k.strip())
    assert after["spatial"] == sorted(p for p in before["spatial"] if p.strip())
    assert sorted(a["name"] for a in after["contributors"]) == sorted(a["name"] for a in before["contributors"])
    assert [a["identifier"] for a in after["creators"]] == ["https://ror.org/05k4v5r53", "https://orcid.org/0000-0002-1825-0097"]


def test_a_second_round_trip_changes_nothing(client, fake):
    fid, saved = _saved(client)
    first = _open(client, saved["uuid"])["file_id"]
    original, reopened = _cdif_graph(client, fid), _cdif_graph(client, first)
    _, only_original, only_reopened = graph_diff(to_isomorphic(original), to_isomorphic(reopened))
    # What differs is the order of contributors and places, so their nodes swap ids.
    touched = {str(o) for _, p, o in only_original
               if isinstance(o, Literal) and str(p).endswith(("name", "roleName", "termCode"))}
    assert touched <= {"Germany", "Norway", "Doe, John", "Roe, Richard", "Fieldwork Ltd", "NoSuchRole", "Data collector", "DataCollector"}
    assert len(only_original) == len(only_reopened)

    # Saved again and opened again: now nothing moves.
    assert client.post(f"/api/files/{first}/qlever", json={}).json()["uuid"] == saved["uuid"]
    second = _open(client, saved["uuid"])["file_id"]
    assert isomorphic(_cdif_graph(client, first), _cdif_graph(client, second))


def test_the_record_count_is_kept_until_rows_are_added(client, fake):
    fid, saved = _saved(client)
    opened = _open(client, saved["uuid"])["file_id"]
    doc = json.loads(client.post(f"/api/files/{opened}/generate", json={"max_rows": 0}).content)
    assert {x["recordCount"] for x in doc["DDICDIModels"] if "recordCount" in x} == {2420}
    assert client.post(f"/api/files/{opened}/rows", json={"values": {}}).status_code == 201
    doc = json.loads(client.post(f"/api/files/{opened}/generate", json={"max_rows": 0}).content)
    assert {x["recordCount"] for x in doc["DDICDIModels"] if "recordCount" in x} == {1}


def test_open_unknown_and_bad_ids(client, fake):
    assert client.post(f"/api/qlever/documents/{qlever.new_uuid()}/open").status_code == 404
    assert client.post("/api/qlever/documents/nope/open").status_code == 400


@pytest.mark.parametrize("roles", [{"idno": "identifier"}, {"cntry": "attribute", "essround": "attribute"}])
def test_other_role_sets_survive(client, fake, roles):
    fid, saved = _saved(client, **roles)
    after = _meta(client, _open(client, saved["uuid"])["file_id"])
    for name, role in roles.items():
        assert name in getattr(after.roles, role)


@live
def test_open_through_a_real_qlever(client, live_store):  # noqa: F811
    fid = _upload(client).json()["file_id"]
    saved = client.post(f"/api/files/{fid}/qlever", json={"include_statistics": True}).json()
    live_store.append(saved["uuid"])
    after = _meta(client, _open(client, saved["uuid"])["file_id"])
    before = _meta(client, fid)
    assert [dataclasses.asdict(v) for v in after.variables] == [dataclasses.asdict(v) for v in before.variables]
    assert after.source_rows == before.number_rows


# -- statistics ---------------------------------------------------------------------


@pytest.mark.parametrize("weight", [None, "dweight"])
def test_saved_statistics_come_back_and_are_written_again(client, fake, weight):
    fid = _upload(client).json()["file_id"]
    body = {"include_statistics": True, "statistics_weight": weight}
    saved = client.post(f"/api/files/{fid}/qlever", json=body).json()
    opened = _open(client, saved["uuid"])["file_id"]

    def cdif(f):
        r = client.post(f"/api/files/{f}/generate", params={"format": "cdif"}, json={"max_rows": 0, **body})
        return qlever.cdif_graph(json.loads(r.content))

    original, reopened = cdif(fid), cdif(opened)
    if not isomorphic(original, reopened):
        _, a, b = graph_diff(to_isomorphic(original), to_isomorphic(reopened))
        pytest.fail(f"original only: {sorted(a)[:4]}\nreopened only: {sorted(b)[:4]}")


def test_statistics_tab_shows_the_saved_ones(client, fake):
    fid = _upload(client).json()["file_id"]
    saved = client.post(f"/api/files/{fid}/qlever", json={"include_statistics": True}).json()
    opened = _open(client, saved["uuid"])["file_id"]
    live = client.get(f"/api/files/{fid}/statistics").json()
    shown = client.get(f"/api/files/{opened}/statistics").json()
    assert shown["saved"] is True and live["saved"] is False
    by_name = {v["name"]: v for v in shown["variables"]}
    ppltrst = next(v for v in live["variables"] if v["name"] == "ppltrst")
    assert by_name["ppltrst"]["valid_n"] == ppltrst["valid_n"]
    assert {s["name"]: s["value"] for s in by_name["ppltrst"]["stats"]}["mean"] == \
        {s["name"]: s["value"] for s in ppltrst["stats"]}["mean"]
    cats = client.get(f"/api/files/{opened}/statistics/ppltrst/categories", params={"sort": "code", "limit": 3}).json()
    live_cats = client.get(f"/api/files/{fid}/statistics/ppltrst/categories", params={"sort": "code", "limit": 3}).json()
    assert [(c["code"], c["count"]) for c in cats["categories"]] == [(c["code"], c["count"]) for c in live_cats["categories"]]
    assert cats["truncated"] is True


def test_saved_statistics_follow_a_rename_and_give_way_to_data(client, fake):
    fid = _upload(client).json()["file_id"]
    saved = client.post(f"/api/files/{fid}/qlever", json={"include_statistics": True}).json()
    opened = _open(client, saved["uuid"])["file_id"]
    assert client.patch(f"/api/files/{opened}/variables/ppltrst", json={"new_name": "trust"}).status_code == 200
    names = {v["name"] for v in client.get(f"/api/files/{opened}/statistics").json()["variables"]}
    assert "trust" in names and "ppltrst" not in names
    # Once the session has rows, statistics come from them again.
    client.post(f"/api/files/{opened}/rows", json={"values": {"trust": "5"}})
    stats = client.get(f"/api/files/{opened}/statistics").json()
    assert stats["saved"] is False and stats["total_rows"] == 1


@live
def test_statistics_through_a_real_qlever(client, live_store):  # noqa: F811
    from tests.test_qlever import _canonical

    fid = _upload(client).json()["file_id"]
    body = {"include_statistics": True, "statistics_weight": "dweight"}
    saved = client.post(f"/api/files/{fid}/qlever", json=body).json()
    live_store.append(saved["uuid"])
    opened = _open(client, saved["uuid"])["file_id"]

    def cdif(f):
        r = client.post(f"/api/files/{f}/generate", params={"format": "cdif"}, json={"max_rows": 0, **body})
        return _canonical(qlever.cdif_graph(json.loads(r.content)))

    assert isomorphic(cdif(fid), cdif(opened))  # equal to QLever's 12-13 significant digits
