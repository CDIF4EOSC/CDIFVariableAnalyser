"""AI enrichment: payload shape, n8n call pattern, retries, and the suggestions-only route."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from ddicdi import enrich
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings
from ddicdi.models import MissingRange, Variable
from tests.conftest import ESS11_SAV

UNIT = "http://publications.europa.eu/resource/authority/measurement-unit/HUR"
ELSST = "https://elsst.cessda.eu/id/6/ac98f3f1-4846-44af-8cf3-e980cf47b27c"


def _var(name="v1", **kw) -> Variable:
    return Variable(name=name, **kw)


def test_variable_input_caps_value_labels_and_splits_missing():
    labels = {str(i): f"label {i}" for i in range(1, 21)} | {"88": "Don't know"}
    v = _var(label="Hours", storage_type="double", format="F2.0", measure="ordinal", numeric=True,
             value_labels=labels, missing_ranges=[MissingRange(77.0, 77.0), MissingRange(88.0, 99.0)])
    item = enrich.variable_input(v)
    assert item == {
        "variable_name": "v1",
        "variable_label": "Hours",
        "variable_datatype": "double",
        "variable_format": "F2.0",
        "variable_measure": "ordinal",
        "variable_value_labels": [{"value": str(i), "label": f"label {i}"} for i in range(1, 16)],
        "variable_value_labels_total": 20,  # substantive only: the missing code 88 is not counted
        "variable_missing_values": ["77", "88-99"],
    }
    # empty fields are left out; an unknown measure is not sent
    assert enrich.variable_input(_var()) == {"variable_name": "v1", "variable_datatype": "string"}
    # no legacy keys: the workflows reject them
    assert not {"label", "description"} & set(item)


def test_normalisers():
    assert enrich.normalize_unit("") is None
    assert enrich.normalize_unit("HUR") == UNIT
    assert enrich.normalize_unit(UNIT) == UNIT
    assert enrich.normalize_unit("not a unit") is None
    assert enrich.normalize_concepts([{"uri": ELSST, "pref_label": "TIME"}, {"uri": ELSST}, {"uri": "x"}, "junk"]) == [
        {"uri": ELSST, "pref_label": "TIME"}
    ]


def test_normalize_role_accepts_strings_lists_and_aliases():
    assert enrich.normalize_role("identifier") == "identifier"
    assert enrich.normalize_role("Attribute, Measure") == "measure,attribute"  # canonical order
    assert enrich.normalize_role(["attribute", "identifier"]) == "identifier,attribute"
    assert enrich.normalize_role("Dimension") == "identifier"
    assert enrich.normalize_role("IdentifierComponent") == "identifier"
    assert enrich.role_from_result({"variable_name": "x", "component_role": "AttributeComponent", "status": "ok"}) == "attribute"
    assert enrich.normalize_role("") is None and enrich.normalize_role("weight") is None and enrich.normalize_role(3) is None
    assert enrich.role_from_result({"variable_name": "x", "variable_role": "measure"}) == "measure"
    assert enrich.role_from_result({"variable_name": "x", "roles": ["measure", "attribute"]}) == "measure,attribute"
    assert enrich.role_from_result({"variable_name": "x"}) is None


def test_normalize_functions_accepts_lists_strings_and_case():
    assert enrich.normalize_functions(["Weight"]) == ["Weight"]
    assert enrich.normalize_functions(["weight", "WEIGHT", "SamplingDesign"]) == ["Weight", "SamplingDesign"]
    assert enrich.normalize_functions("UnitIdentifier, TemporalDimension") == ["UnitIdentifier", "TemporalDimension"]
    assert enrich.normalize_functions([]) == [] and enrich.normalize_functions("") == [] and enrich.normalize_functions(3) == []
    assert enrich.normalize_functions(["not a name!"]) == []
    assert enrich.normalize_functions(["FutureTerm"]) == ["FutureTerm"]  # unknown but well-formed: keep
    assert enrich.functions_from_result({"variable_name": "x", "variable_function": ["Weight"], "status": "ok"}) == ["Weight"]
    assert enrich.functions_from_result({"variable_name": "x"}) is None


def test_normalize_measure_lowercases_and_maps_aliases():
    assert enrich.normalize_measure("Scale") == "scale"
    assert enrich.normalize_measure("ORDINAL") == "ordinal"
    assert enrich.normalize_measure(" nominal ") == "nominal"
    assert enrich.normalize_measure("interval") == "scale" and enrich.normalize_measure("ratio") == "scale"
    assert enrich.normalize_measure("") is None and enrich.normalize_measure("unknown") is None and enrich.normalize_measure(3) is None
    assert enrich.measure_from_result({"variable_name": "x", "measure": "Ordinal", "status": "ok"}) == "ordinal"
    assert enrich.measure_from_result({"variable_name": "x", "measurement_level": "Scale"}) == "scale"
    assert enrich.measure_from_result({"variable_name": "x"}) is None


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def configured(monkeypatch):
    monkeypatch.setattr(settings, "n8n_bearer_key", "Bearer test")
    monkeypatch.setattr(settings, "n8n_unit_url", "https://n8n.test/units")
    monkeypatch.setattr(settings, "n8n_concept_url", "https://n8n.test/concepts")
    monkeypatch.setattr(settings, "n8n_role_url", "https://n8n.test/roles")
    monkeypatch.setattr(settings, "n8n_function_url", "https://n8n.test/functions")
    monkeypatch.setattr(settings, "n8n_measure_url", "https://n8n.test/measures")
    monkeypatch.setattr(enrich, "BACKOFF", 0.0)


def test_enrich_call_pattern(configured):
    calls: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        assert request.headers["authorization"] == "Bearer test"
        names = [v["variable_name"] for v in body["variables"]]
        if request.url.path == "/units":
            return httpx.Response(200, json={"results": [{"variable_name": n, "unit_of_measure": "HUR" if n == "a" else ""} for n in names]})
        if request.url.path == "/roles":  # real shape: one-element array, *Component names, status
            rows = [{"variable_name": n, "component_role": "IdentifierComponent" if n == "b" else "MeasureComponent", "status": "ok"} for n in names]
            return httpx.Response(200, json=[{"results": rows, "ok": len(rows), "failed": 0, "total": len(rows)}])
        if request.url.path == "/functions":  # real shape: variable_function is a (possibly empty) list
            rows = [{"variable_name": n, "variable_function": ["Weight"] if n == "a" else [], "status": "ok"} for n in names]
            return httpx.Response(200, json={"results": rows, "ok": len(rows), "failed": 0, "total": len(rows)})
        for v in body["variables"]:  # every kind gets the same shared item
            assert v == enrich.variable_input(_var(v["variable_name"]))
        if request.url.path == "/measures":  # real shape: one-element array, capitalised level, status
            rows = [{"variable_name": n, "measure": "Scale" if n == "a" else "Nominal", "status": "ok"} for n in names]
            return httpx.Response(200, json=[{"results": rows, "ok": len(rows), "failed": 0, "total": len(rows)}])
        assert len(names) == 1  # concepts: one variable per request
        return httpx.Response(200, json={"results": [{"variable_name": names[0], "elsst_concepts": [{"uri": ELSST, "pref_label": "TIME"}]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = _run(enrich.enrich([_var("a"), _var("b")], client=client))
    assert [p for p, _ in calls if p == "/units"] == ["/units"]
    assert [p for p, _ in calls if p == "/roles"] == ["/roles"]  # roles: one batched call
    assert [p for p, _ in calls if p == "/functions"] == ["/functions"]
    assert [p for p, _ in calls if p == "/measures"] == ["/measures"]
    assert sorted(b["variables"][0]["variable_name"] for p, b in calls if p == "/concepts") == ["a", "b"]
    assert res.errors == []
    assert res.suggestions["a"] == {
        "name": "a", "unit_of_measure": UNIT, "concepts": [{"uri": ELSST, "pref_label": "TIME"}], "role": "measure", "functions": ["Weight"],
        "measure": "scale",
    }
    assert res.suggestions["b"]["measure"] == "nominal"
    assert res.suggestions["b"]["unit_of_measure"] is None
    assert res.suggestions["b"]["role"] == "identifier"
    assert res.suggestions["b"]["functions"] == []  # "none applies" is a real answer, kept so the UI can show it

    # only roles requested: no other webhook is called
    calls.clear()
    res = _run(enrich.enrich([_var("a")], ["role"], client=client))
    assert [p for p, _ in calls] == ["/roles"]
    assert res.suggestions["a"] == {"name": "a", "role": "measure"}


def test_batched_calls_and_failed_status(configured, monkeypatch):
    monkeypatch.setattr(enrich, "BATCH_SIZE", 2)
    sizes: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        names = [v["variable_name"] for v in json.loads(request.content)["variables"]]
        sizes.append(len(names))
        rows = [{"variable_name": n, "component_role": "MeasureComponent", "status": "ok" if n != "v3" else "failed"} for n in names]
        return httpx.Response(200, json=[{"results": rows}])

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    res = _run(enrich.enrich([_var(f"v{i}") for i in range(5)], ["role"], client=client))
    assert sorted(sizes) == [1, 2, 2]
    assert sorted(res.suggestions) == ["v0", "v1", "v2", "v4"]
    assert res.errors == [{"name": "v3", "kind": "role", "message": "n8n status 'failed'"}]


def test_measure_outside_vocabulary_is_an_error(configured):
    def handler(request: httpx.Request) -> httpx.Response:
        names = [v["variable_name"] for v in json.loads(request.content)["variables"]]
        rows = [{"variable_name": n, "measure": "Ordinal" if n == "good" else "Likert", "status": "ok"} for n in names]
        return httpx.Response(200, json=[{"results": rows}])

    res = _run(enrich.enrich([_var("good"), _var("odd")], ["measure"], client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert res.suggestions == {"good": {"name": "good", "measure": "ordinal"}}
    assert res.errors == [{"name": "odd", "kind": "measure", "message": "no usable value in result"}]


def test_retry_on_5xx_but_not_4xx(configured):
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"results": [{"variable_name": "a", "unit_of_measure": "MTS"}]})

    res = _run(enrich.enrich([_var("a")], ["unit"], client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert hits["n"] == 2 and res.suggestions["a"]["unit_of_measure"].endswith("/MTS")

    hits["n"] = 0
    bad = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (hits.__setitem__("n", hits["n"] + 1), httpx.Response(401, text="nope"))[1]))
    res = _run(enrich.enrich([_var("a")], ["unit"], client=bad))
    assert hits["n"] == 1 and res.suggestions == {} and res.errors[0]["kind"] == "unit" and "401" in res.errors[0]["message"]


def test_partial_concept_failure_keeps_other_suggestions(configured):
    def handler(request: httpx.Request) -> httpx.Response:
        name = json.loads(request.content)["variables"][0]["variable_name"]
        if name == "bad":
            return httpx.Response(200, json={"results": []})  # the n8n empty-body bug, every time
        return httpx.Response(200, json={"results": [{"variable_name": name, "elsst_concepts": [{"uri": ELSST, "pref_label": "TIME"}]}]})

    res = _run(enrich.enrich([_var("ok"), _var("bad")], ["concept"], client=httpx.AsyncClient(transport=httpx.MockTransport(handler))))
    assert list(res.suggestions) == ["ok"]
    assert res.errors == [{"name": "bad", "kind": "concept", "message": "empty or mismatched result"}]


def test_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "n8n_bearer_key", "")
    with pytest.raises(enrich.NotConfigured):
        _run(enrich.enrich([_var()]))


# -- route ------------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fid(client):
    with ESS11_SAV.open("rb") as fh:
        r = client.post("/api/files", files={"file": (ESS11_SAV.name, fh)})
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


def test_enrich_route_returns_suggestions_without_saving(client, fid, monkeypatch):
    seen = {}

    async def fake(variables, kinds, *, client=None):
        seen["names"] = [v.name for v in variables]
        seen["kinds"] = list(kinds)
        res = enrich.EnrichResult()
        res.suggestions["ppltrst"] = {"name": "ppltrst", "unit_of_measure": UNIT, "concepts": [{"uri": ELSST, "pref_label": "TRUST"}]}
        res.errors.append({"name": "cntry", "kind": "concept", "message": "empty or mismatched result"})
        return res

    monkeypatch.setattr(enrich, "enrich", fake)
    monkeypatch.setattr(settings, "n8n_bearer_key", "Bearer x")
    assert client.get("/api/info").json()["ai_enrichment"] is True

    r = client.post(f"/api/files/{fid}/enrich", json={"variables": ["ppltrst", "cntry"], "kinds": ["unit", "concept"]})
    assert r.status_code == 200, r.text
    assert seen == {"names": ["cntry", "ppltrst"], "kinds": ["unit", "concept"]}
    body = r.json()
    assert body["suggestions"] == [{"name": "ppltrst", "unit_of_measure": UNIT, "concepts": [{"uri": ELSST, "pref_label": "TRUST"}], "role": None, "functions": None, "measure": None}]
    assert body["errors"][0]["name"] == "cntry"
    # nothing persisted
    v = next(x for x in client.get(f"/api/files/{fid}").json()["variables"] if x["name"] == "ppltrst")
    assert v["unit_of_measure"] is None and v["concepts"] == []

    r = client.post(f"/api/files/{fid}/enrich", json={"kinds": ["role"]})
    assert r.status_code == 200 and seen["kinds"] == ["role"]
    r = client.post(f"/api/files/{fid}/enrich", json={"kinds": ["function"]})
    assert r.status_code == 200 and seen["kinds"] == ["function"]
    r = client.post(f"/api/files/{fid}/enrich", json={"kinds": ["measure"]})
    assert r.status_code == 200 and seen["kinds"] == ["measure"]
    r = client.post(f"/api/files/{fid}/enrich", json={})
    assert r.status_code == 200 and seen["kinds"] == ["unit", "concept", "role", "function", "measure"]
    assert client.post(f"/api/files/{fid}/enrich", json={"kinds": ["weight"]}).status_code == 422
    assert client.post(f"/api/files/{fid}/enrich", json={"variables": ["nope"]}).status_code == 400
    assert client.post(f"/api/files/{fid}/enrich", json={"kinds": []}).status_code == 400


def test_enrich_route_503_when_unconfigured(client, fid, monkeypatch):
    monkeypatch.setattr(settings, "n8n_bearer_key", "")
    assert client.get("/api/info").json()["ai_enrichment"] is False
    r = client.post(f"/api/files/{fid}/enrich", json={})
    assert r.status_code == 503 and "DDI_N8N_BEARER_KEY" in r.json()["detail"]
