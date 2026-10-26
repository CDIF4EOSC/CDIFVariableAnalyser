"""CDIF output: the DDI-CDI document through the vendored, extended CDIF converter."""

import json

import pytest

from ddicdi.cdi.jsonld import GenerateOptions, build_document
from ddicdi.cdif import convert_document
from ddicdi.roles import parse_roles
from tests.test_api import _upload, client  # noqa: F401  (fixture)


@pytest.fixture()
def cdif(ess11):
    before = ess11.meta.roles
    ess11.meta.roles = parse_roles(ess11.meta, {"idno": "identifier"})
    yield convert_document(build_document(ess11, options=GenerateOptions(max_rows=0)), "ESS11-subset")
    ess11.meta.roles = before


def _var(doc, name):
    return next(v for v in doc["schema:variableMeasured"] if v["schema:name"] == name)


def test_labels_become_descriptions(cdif):
    assert _var(cdif, "ppltrst")["schema:description"] == "Most people can be trusted or you can't be too careful"


def test_code_lists_and_sentinels(cdif):
    ppltrst = _var(cdif, "ppltrst")
    scheme = ppltrst["cdi:takesSubstantiveValuesFrom"]["cdif:takesValuesFrom"]["cdif:references"]
    first = scheme["skos:hasTopConcept"][0]
    assert first["skos:notation"] == "0" and first["skos:prefLabel"] == "You can't be too careful"
    sentinel = ppltrst["cdi:takesSentinelValuesFrom"][0]
    assert sentinel["@type"] == ["cdif:SentinelValueDomain"]
    notations = [c["skos:notation"] for c in sentinel["cdif:takesValuesFrom"]["cdif:references"]["skos:hasTopConcept"]]
    assert notations == ["77", "88", "99"]


def test_structured_distribution(cdif):
    dist = cdif["schema:distribution"][0]
    assert "cdi:StructuredDataSet" in dist["@type"] and dist["schema:encodingFormat"] == ["application/x-spss-sav"]
    rows = next(p for p in dist["schema:additionalProperty"] if p["schema:name"] == "countRows")
    assert rows["schema:value"] == 2420
    mappings = dist["cdif:hasPhysicalMapping"]
    assert len(mappings) == 13 and mappings[0]["@type"] == ["cdif:LocatorMapping"] and mappings[0]["cdi:locator"] == "name"
    key = dist["cdi:isStructuredBy"]["cdif:has_PrimaryKey"]
    assert key["@type"] == ["cdif:Key"] and key["cdif:isComposedOf"][0]["cdi:indexes"] == {"@id": "#instanceVariable-idno"}
    conforms = [c["@id"] for c in cdif["schema:subjectOf"]["dcterms:conformsTo"]]
    assert "https://w3id.org/cdif/data_structure/1.1" in conforms


def test_generate_cdif_download(client):  # noqa: F811
    fid = _upload(client).json()["file_id"]
    r = client.post(f"/api/files/{fid}/generate", params={"format": "cdif"}, json={"max_rows": 5})
    assert r.status_code == 200, r.text
    assert r.headers["content-disposition"] == 'attachment; filename="ESS11-subset_CDIF.json"'
    doc = json.loads(r.content)
    assert doc["@type"] == ["schema:Dataset"] and len(doc["schema:variableMeasured"]) == 13
    assert client.post(f"/api/files/{fid}/generate", params={"format": "xml"}, json={}).status_code == 422
