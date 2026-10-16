"""Editor endpoints: variables, cells, rows, roles and the preview output."""

import pytest
from fastapi.testclient import TestClient

from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from tests.conftest import ESS11_SAV


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


def _doc(client, fid, max_rows=2):
    r = client.post(f"/api/files/{fid}/output", json={"max_rows": max_rows})
    assert r.status_code == 200, r.text
    return r.json()


def _by_id(doc, id_):
    return next(x for x in doc["DDICDIModels"] + doc.get("@included", []) if x["@id"] == id_)


def _label(element):
    return element["displayLabel"]["locationVariant"]["entryValue"]


def test_patch_variable_updates_output(client, fid):
    r = client.patch(
        f"/api/files/{fid}/variables/ppltrst",
        json={"label": "Trust in people", "measure": "scale", "missing": [{"lo": 77, "hi": 99}], "role": "measure,attribute"},
    )
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["label"] == "Trust in people" and v["measure"] == "scale"
    assert v["missing"] == [{"lo": "77", "hi": "99"}] and v["default_role"] == "measure,attribute"

    doc = _doc(client, fid)
    assert _label(_by_id(doc, "#instanceVariable-ppltrst")) == "Trust in people"
    assert any(x["@type"] == "AttributeComponent" for x in doc["DDICDIModels"])
    # roles survive a reload of the metadata
    info = client.get(f"/api/files/{fid}").json()
    assert next(x for x in info["variables"] if x["name"] == "ppltrst")["default_role"] == "measure,attribute"


UNIT = "http://publications.europa.eu/resource/authority/measurement-unit/HUR"
ELSST = "https://elsst.cessda.eu/id/6/ac98f3f1-4846-44af-8cf3-e980cf47b27c"
OTHER = "https://example.org/vocab/trust"


def test_patch_unit_and_concepts(client, fid):
    r = client.patch(
        f"/api/files/{fid}/variables/ppltrst",
        json={"unit_of_measure": UNIT, "concepts": [{"uri": ELSST, "pref_label": "TRUST"}, {"uri": OTHER}, {"uri": ELSST}]},
    )
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["unit_of_measure"] == UNIT
    assert v["concepts"] == [{"uri": ELSST, "pref_label": "TRUST"}, {"uri": OTHER, "pref_label": ""}]

    doc = _doc(client, fid, max_rows=0)
    assert any("owl" in c for c in doc["@context"] if isinstance(c, dict))
    iv = _by_id(doc, "#instanceVariable-ppltrst")
    assert iv["describedUnitOfMeasure"] == {"@type": "ControlledVocabularyEntry", "entryValue": UNIT}
    cid = "#concept-ppltrst-ac98f3f1-4846-44af-8cf3-e980cf47b27c"
    assert iv["uses_Concept"] == [cid, "#concept-ppltrst-trust"]
    concept = _by_id(doc, cid)
    assert concept["@type"] == "Concept" and concept in doc["DDICDIModels"]
    assert concept["name"] == {"@type": "ObjectName", "name": "TRUST"}
    assert concept["externalDefinition"]["nonDdiReference"] == {
        "@type": "NonDdiIdentifier", "managingAgency": "ddi", "value": "ac98f3f1-4846-44af-8cf3-e980cf47b27c",
        "type": "int.cessda.elsst", "version": "6",
    }
    assert concept["owl:sameAs"] == {"@id": ELSST}
    assert "type" not in _by_id(doc, "#concept-ppltrst-trust")["externalDefinition"]["nonDdiReference"]

    # survives reload, then clearing removes everything again
    info = client.get(f"/api/files/{fid}").json()
    assert next(x for x in info["variables"] if x["name"] == "ppltrst")["unit_of_measure"] == UNIT
    r = client.patch(f"/api/files/{fid}/variables/ppltrst", json={"unit_of_measure": "", "concepts": []})
    assert r.status_code == 200 and r.json()["unit_of_measure"] is None and r.json()["concepts"] == []
    doc = _doc(client, fid, max_rows=0)
    iv = _by_id(doc, "#instanceVariable-ppltrst")
    assert "describedUnitOfMeasure" not in iv and "uses_Concept" not in iv
    assert not any(x["@type"] == "Concept" for x in doc["DDICDIModels"])
    assert not any("owl" in c for c in doc["@context"] if isinstance(c, dict))

    assert client.patch(f"/api/files/{fid}/variables/ppltrst", json={"unit_of_measure": "hours"}).status_code == 400
    assert client.patch(f"/api/files/{fid}/variables/ppltrst", json={"concepts": [{"uri": "trust"}]}).status_code == 400


def test_roles_put_and_primary_key(client, fid):
    r = client.put(f"/api/files/{fid}/roles", json={"roles": {"idno": "identifier", "cntry": "attribute"}})
    assert r.status_code == 200, r.text
    roles = {v["name"]: v["default_role"] for v in r.json()["variables"]}
    assert roles["idno"] == "identifier" and roles["cntry"] == "attribute" and roles["ppltrst"] == "measure"
    doc = _doc(client, fid, max_rows=0)
    assert _by_id(doc, "#primaryKey")
    # generate without roles in the body uses the stored roles
    r = client.post(f"/api/files/{fid}/generate", json={"max_rows": 0})
    assert b'"PrimaryKey"' in r.content
    assert client.put(f"/api/files/{fid}/roles", json={"roles": {"nope": "measure"}}).status_code == 400


def test_add_edit_delete_variable(client, fid):
    r = client.post(
        f"/api/files/{fid}/variables",
        json={
            "name": "region",
            "label": "NUTS-2 region",
            "format": "A5",
            "type": "string",
            "role": "attribute",
            "value_labels": {"AT13": "Wien"},
            "fill": "constant",
            "fill_value": "AT13",
        },
    )
    assert r.status_code == 201, r.text
    info = client.get(f"/api/files/{fid}", params={"preview_rows": 2}).json()
    assert info["number_variables"] == 14 and info["preview"][0]["region"] == "AT13"
    assert info["number_rows"] == 2420

    doc = _doc(client, fid)
    iv = _by_id(doc, "#instanceVariable-region")
    assert _label(iv) == "NUTS-2 region" and iv["physicalDataType"]["entryValue"] == "string"
    pm = _by_id(doc, "#locatorMapping-region")
    assert pm["format"]["entryValue"] == "A5" and pm["maximumLength"] == 5
    assert _by_id(doc, "#instanceValue-0-region")["content"]["content"] == "AT13"
    assert _by_id(doc, "#code-region-AT13")["denotes"] == "#category-region-AT13"

    # copy of a column, inserted at the front
    r = client.post(
        f"/api/files/{fid}/variables",
        json={"name": "idno_copy", "type": "double", "fill": "copy", "fill_value": "idno", "position": 0},
    )
    assert r.status_code == 201, r.text
    p = client.get(f"/api/files/{fid}/preview", params={"rows": 1}).json()
    assert p["columns"][0] == "idno_copy" and p["rows"][0][0] == p["rows"][0][p["columns"].index("idno")]

    # rename + delete
    r = client.patch(f"/api/files/{fid}/variables/idno_copy", json={"new_name": "idno2"})
    assert r.status_code == 200 and r.json()["name"] == "idno2"
    r = client.delete(f"/api/files/{fid}/variables/idno2")
    assert r.status_code == 200 and r.json()["number_variables"] == 14
    assert "idno2" not in client.get(f"/api/files/{fid}/preview").json()["columns"]

    # validation
    assert client.post(f"/api/files/{fid}/variables", json={"name": "region"}).status_code == 400
    assert client.post(f"/api/files/{fid}/variables", json={"name": "1 bad"}).status_code == 400
    assert client.patch(f"/api/files/{fid}/variables/nope", json={"label": "x"}).status_code == 400


def test_edit_cells_and_rows(client, fid):
    before = client.get(f"/api/files/{fid}/preview", params={"rows": 2}).json()
    col = before["columns"].index("ppltrst")
    r = client.patch(f"/api/files/{fid}/rows/1", json={"values": {"ppltrst": "8", "cntry": "NO"}})
    assert r.status_code == 200, r.text
    assert r.json()["row"][col] == "8"
    after = client.get(f"/api/files/{fid}/preview", params={"rows": 2}).json()
    assert after["rows"][0] == before["rows"][0] and after["rows"][1][col] == "8"
    assert after["total_rows"] == 2420

    doc = _doc(client, fid)
    assert _by_id(doc, "#instanceValue-1-ppltrst")["content"]["content"] == "8"
    assert _by_id(doc, "#instanceValue-1-cntry")["content"]["content"] == "NO"

    # a sentinel code routes to the sentinel domain
    client.patch(f"/api/files/{fid}/rows/1", json={"values": {"ppltrst": "88"}})
    doc = _doc(client, fid)
    assert _by_id(doc, "#instanceValue-1-ppltrst")["hasValueFrom_ValueDomain"] == "#sentinelValueDomain-ppltrst"

    r = client.post(f"/api/files/{fid}/rows", json={"values": {"idno": "99999", "cntry": "SE"}})
    assert r.status_code == 201 and r.json() == {"index": 2420, "total_rows": 2421}
    p = client.get(f"/api/files/{fid}/preview", params={"rows": 1, "offset": 2420}).json()
    assert p["rows"][0][before["columns"].index("idno")] == "99999" and p["rows"][0][col] == ""

    assert client.delete(f"/api/files/{fid}/rows/2420").json() == {"total_rows": 2420}
    assert client.patch(f"/api/files/{fid}/rows/5000", json={"values": {"idno": "1"}}).status_code == 400
    assert client.patch(f"/api/files/{fid}/rows/0", json={"values": {"nope": "1"}}).status_code == 400


def test_output_is_jsonld(client, fid):
    r = client.post(f"/api/files/{fid}/output", json={"max_rows": 1})
    assert r.status_code == 200 and r.headers["content-type"] == "application/ld+json"
    assert b"StructuredDataSet" in r.content


def test_patch_functions_validates_and_clears(client, fid):
    r = client.patch(f"/api/files/{fid}/variables/ppltrst", json={"functions": ["weight", "Weight", "SamplingDesign"]})
    assert r.status_code == 200, r.text
    assert r.json()["functions"] == ["Weight", "SamplingDesign"]  # canonical case, deduplicated
    info = client.get(f"/api/files/{fid}").json()
    assert next(x for x in info["variables"] if x["name"] == "ppltrst")["functions"] == ["Weight", "SamplingDesign"]

    iv = _by_id(_doc(client, fid, max_rows=0), "#instanceVariable-ppltrst")
    assert iv["function"] == [
        {"@type": "ControlledVocabularyEntry", "entryValue": "Weight"},
        {"@type": "ControlledVocabularyEntry", "entryValue": "SamplingDesign"},
    ]

    assert client.patch(f"/api/files/{fid}/variables/ppltrst", json={"functions": ["no good!"]}).status_code == 400
    r = client.patch(f"/api/files/{fid}/variables/ppltrst", json={"functions": []})
    assert r.status_code == 200 and r.json()["functions"] == []
    assert "function" not in _by_id(_doc(client, fid, max_rows=0), "#instanceVariable-ppltrst")
    r = client.post(f"/api/files/{fid}/variables", json={"name": "wgt", "type": "double", "functions": ["Weight"]})
    assert r.status_code == 201 and r.json()["functions"] == ["Weight"]


def test_format_decimals_must_be_smaller_than_width():
    import pytest

    from ddicdi.editing import EditError, check_format

    assert check_format(" F5.2 ") == "F5.2"
    assert check_format("A14") == "A14"
    assert check_format("F1.0") == "F1.0"
    assert check_format("%9.0g") == "%9.0g"
    assert check_format("BEST12.") == "BEST12."
    with pytest.raises(EditError, match="too large for the field width"):
        check_format("F3.3")
    with pytest.raises(EditError, match="too large for the field width"):
        check_format("F2.5")
    with pytest.raises(EditError, match="at least 1"):
        check_format("A0")
