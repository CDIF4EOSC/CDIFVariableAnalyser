"""CDIF output: the DDI-CDI document through the vendored, extended CDIF converter."""

import hashlib
import json
from datetime import date

import pytest

from ddicdi.cdi.jsonld import GenerateOptions, build_document
from ddicdi.cdif import convert_document
from ddicdi.importers import import_file
from ddicdi.roles import parse_roles
from tests.conftest import ESS11_SAV
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


def test_output_preview_in_cdif(client):  # noqa: F811
    fid = _upload(client).json()["file_id"]
    r = client.post(f"/api/files/{fid}/output", params={"format": "cdif"}, json={"max_rows": 5})
    assert r.status_code == 200, r.text
    doc = r.json()
    assert "DDICDIModels" not in doc and len(doc["schema:variableMeasured"]) == 13


INFO = {
    "title": "ESS Round 11 (subset)",
    "description": "A subset of ESS11 used to test the converter.",
    "identifier": "https://doi.org/10.21338/ess11e04_2",
    "license": "https://creativecommons.org/licenses/by/4.0/",
    "keywords": ["social trust", " ", "politics"],
    "date_published": "2024-06",
    "date_modified": "2025-11-03",
    "creators": [
        {"name": "ESS ERIC", "kind": "organization", "identifier": "05k4v5r53"},
        {"name": "Doe, Jane", "identifier": "0000-0002-1825-0097", "affiliation": "Sikt",
         "affiliation_id": "https://ror.org/04qtnsw81", "email": "jane@example.org"},
    ],
    "publisher": {"name": "Sikt", "kind": "organization", "identifier": "https://ror.org/04qtnsw81"},
    "record_id": "https://example.org/records/ess11-subset",
    "contributors": [
        {"name": "Fieldwork Ltd", "kind": "organization", "role": "DataCollector"},
        {"name": "Roe, Richard", "role": "NoSuchRole"},
        {"name": "Doe, John"},
    ],
    "temporal_start": "2023-01-01",
    "temporal_end": "2024-12-31",
    "spatial": ["Norway", " ", "Germany"],
    "funding": [{"funder": "European Commission", "funder_id": "https://ror.org/00k4n6c32", "award": "101057264"}],
}


def test_dataset_info_round_trip_and_cdif(client):  # noqa: F811
    fid = _upload(client).json()["file_id"]
    suggested = client.get(f"/api/files/{fid}").json()["info"]
    today = date.today().isoformat()
    assert suggested["date_published"] == suggested["date_modified"] == today
    assert suggested["title"] and suggested["record_id"] == "urn:ddi-cdi:ESS11-subset"
    assert suggested["creators"] == []
    r = client.put(f"/api/files/{fid}/info", json=INFO)
    assert r.status_code == 200, r.text
    assert client.get(f"/api/files/{fid}/info").json()["creators"][1]["affiliation"] == "Sikt"
    assert client.put(f"/api/files/{fid}/info", json={"date_published": "June 2024"}).status_code == 422

    doc = client.post(f"/api/files/{fid}/output", params={"format": "cdif"}, json={}).json()
    assert doc["@id"] == INFO["record_id"] and doc["schema:name"] == INFO["title"]
    assert doc["schema:subjectOf"]["schema:about"] == {"@id": INFO["record_id"]}
    assert doc["schema:identifier"]["schema:value"] == "10.21338/ess11e04_2"
    assert doc["schema:identifier"]["schema:propertyID"] == {"@id": "https://registry.identifiers.org/registry/doi"}
    assert doc["schema:keywords"] == ["social trust", "politics"]
    assert doc["schema:datePublished"] == "2024-06" and doc["schema:dateModified"] == "2025-11-03"
    org, person = doc["schema:creator"]["@list"]
    assert org["@type"] == ["schema:Organization"] and org["schema:identifier"] == "https://ror.org/05k4v5r53"
    assert person["schema:identifier"] == "https://orcid.org/0000-0002-1825-0097"
    assert person["schema:affiliation"]["schema:name"] == "Sikt"
    assert person["schema:contactPoint"]["schema:email"] == "jane@example.org"
    assert doc["schema:publisher"]["schema:name"] == "Sikt"

    # The DDI-CDI output does not carry the description.
    ddicdi = client.post(f"/api/files/{fid}/output", json={"max_rows": 0}).json()
    assert "schema:creator" not in ddicdi and "dct:title" not in ddicdi


def test_empty_info_keeps_defaults(cdif):
    assert cdif["@id"] == "urn:ddi-cdi:ESS11-subset" and "schema:creator" not in cdif
    assert cdif["schema:identifier"]["schema:propertyID"] == "Uniform Resource Name"
    assert cdif["schema:dateModified"] == "1900-01-01"
    rows = next(p for p in cdif["schema:distribution"][0]["schema:additionalProperty"] if p["schema:name"] == "countRows")
    assert rows["schema:propertyID"] == [{"@id": "http://rdf-vocabulary.ddialliance.org/discovery#caseQuantity"}]
    domain = _var(cdif, "ppltrst")["cdi:takesSubstantiveValuesFrom"]
    assert domain["cdif:displayLabel"] == "ppltrst: substantive values" and domain["cdif:takesValuesFrom"]["schema:name"]


def test_functions(ess11):
    by_name = {v.name: v for v in ess11.meta.variables}
    saved = {n: list(by_name[n].functions) for n in ("dweight", "stratum")}
    by_name["dweight"].functions = ["Weight"]
    by_name["stratum"].functions = ["SamplingDesign"]
    try:
        doc = convert_document(build_document(ess11, options=GenerateOptions(max_rows=0)), "ESS11-subset")
    finally:
        for n, f in saved.items():
            by_name[n].functions = f
    assert _var(doc, "dweight")["cdif:function"] == ["Weight"]
    assert _var(doc, "stratum")["cdif:function"] == ["SamplingDesign"]
    assert "cdif:function" not in _var(doc, "ppltrst")



KGM = "http://publications.europa.eu/resource/authority/measurement-unit/KGM"


def test_unit_uri_and_mapping_details(ess11):
    var = ess11.meta.var("dweight")
    saved = var.unit_of_measure
    var.unit_of_measure = KGM
    try:
        doc = convert_document(build_document(ess11, options=GenerateOptions(max_rows=0)), "ESS11-subset")
    finally:
        var.unit_of_measure = saved
    dweight = _var(doc, "dweight")
    assert dweight["cdif:describedUnitOfMeasure"] == dweight["schema:unitCode"] == {"@id": KGM}
    assert "cdif:simpleUnitOfMeasure" not in dweight
    mapping = next(m for m in doc["schema:distribution"][0]["cdif:hasPhysicalMapping"]
                   if m["cdif:formats_InstanceVariable"] == {"@id": "#instanceVariable-dweight"})
    assert mapping["cdi:decimalPositions"] == 2


def test_csv_null_sequence(qsv, tmp_path):
    csv = tmp_path / "small.csv"
    csv.write_text("id,score\n1,2.5\n2,\n")
    doc = convert_document(build_document(import_file(csv, tmp_path / "work", qsv), options=GenerateOptions(max_rows=0)), "small")
    assert all(m["cdi:nullSequence"] == "" for m in doc["schema:distribution"][0]["cdif:hasPhysicalMapping"])



def test_statistics(ess11):
    doc = convert_document(
        build_document(ess11, options=GenerateOptions(max_rows=0, include_statistics=True, statistics_weight="dweight")),
        "ESS11-subset",
    )
    ppltrst = _var(doc, "ppltrst")
    coll = ppltrst["cdif:isDescribedBy_StatisticsCollection"]
    assert coll["@type"] == ["cdi:StatisticsCollection"] and coll["cdi:hasWeight"] == {"@id": "#instanceVariable-dweight"}
    kinds = {b["cdif:typeOfStatistic"]: b for b in coll["cdif:has_Statistics"]}
    assert {"mean", "minimum", "maximum", "frequency", "percentage"} <= set(kinds)
    assert kinds["mean"]["cdi:statistic"][0]["cdi:isWeighted"] is True
    assert ppltrst["schema:minValue"] == 0 and ppltrst["schema:maxValue"] == 10
    freq = kinds["frequency"]
    cats = freq["cdif:has_CategoryStatistics"]
    assert cats[0]["@type"] == ["cdi:CategoryStatistics"] and cats[0]["cdi:for"]["@type"] == ["cdi:Category"]
    assert freq["cdi:statistic"][0]["cdi:content"] == pytest.approx(sum(c["cdi:statistic"][0]["cdi:content"] for c in cats))
    # Without statistics nothing is attached.
    assert "cdif:isDescribedBy_StatisticsCollection" not in _var(
        convert_document(build_document(ess11, options=GenerateOptions(max_rows=0)), "ESS11-subset"), "ppltrst")


def test_file_facts_and_download_url(client):  # noqa: F811
    fid = _upload(client).json()["file_id"]
    info = client.get(f"/api/files/{fid}").json()
    assert info["file_size"] == ESS11_SAV.stat().st_size
    assert info["file_md5"] == hashlib.md5(ESS11_SAV.read_bytes()).hexdigest()
    client.put(f"/api/files/{fid}/info", json={**info["info"], "content_url": "https://example.org/ess11.sav"})
    doc = client.post(f"/api/files/{fid}/output", params={"format": "cdif"}, json={"include_statistics": True}).json()
    dist = doc["schema:distribution"][0]
    assert dist["schema:contentUrl"] == "https://example.org/ess11.sav"
    assert dist["schema:contentSize"] == str(info["file_size"])
    assert dist["spdx:checksum"]["spdx:checksumValue"] == info["file_md5"]
    assert "cdif:isDescribedBy_StatisticsCollection" in _var(doc, "ppltrst")



def test_contributors_coverage_funding(client):  # noqa: F811
    fid = _upload(client).json()["file_id"]
    assert client.put(f"/api/files/{fid}/info", json=INFO).status_code == 200
    doc = client.post(f"/api/files/{fid}/output", params={"format": "cdif"}, json={}).json()

    collector, curator, plain = doc["schema:contributor"]
    assert collector["@type"] == ["schema:Role"] and collector["schema:roleName"]["schema:termCode"] == "DataCollector"
    assert collector["schema:contributor"]["@type"] == ["schema:Organization"]
    assert curator["schema:roleName"] == "NoSuchRole"  # an unknown code stays a string
    assert plain["@type"] == ["schema:Person"]  # no role: the person itself

    interval, iso = doc["schema:temporalCoverage"]
    assert interval["time:hasBeginning"]["time:inXSDDate"] == "2023-01-01" and iso == "2023-01-01/2024-12-31"
    assert [p["schema:name"] for p in doc["schema:spatialCoverage"]] == ["Norway", "Germany"]
    grant = doc["schema:funding"][0]
    assert grant["schema:funder"]["schema:identifier"] == "https://ror.org/00k4n6c32"
    assert grant["schema:identifier"]["schema:value"] == "101057264"

    assert "vocabularies" in client.get("/api/info").json()
