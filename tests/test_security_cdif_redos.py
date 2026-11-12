"""Issue #4: ARK detection in linear time, and bounded dataset-description fields."""

import time

import pytest

from ddicdi.cdif.ddicdi_jsonld_to_cdif import IDENTIFIERS_ORG, identifier_node, is_ark
from tests.test_api import _upload, client  # noqa: F401  (fixture)

ARK = {"@id": IDENTIFIERS_ORG + "ark"}
DOI = {"@id": IDENTIFIERS_ORG + "doi"}


@pytest.mark.parametrize(
    "ident, property_id",
    [
        ("https://n2t.net/ark:/12345/abc", ARK),
        ("ark:/12345/abc", ARK),
        ("ark:12345/x", ARK),
        ("foo bar/ark:/12345/x", ARK),
        ("doi:10.1234/abc", DOI),
        ("https://doi.org/10.21338/ess11e04_2", DOI),
        ("10.21338/ess11e04_2", DOI),
        ("ark:/1234/too-short-naan", "Local identifier"),
        ("foo ark:/12345/x", "Local identifier"),  # after whitespace, not after '/'
        ("ark:/12345/x trailing", "Local identifier"),
        ("https://example.org/dataset/1", "Web address"),
        ("urn:ddi-cdi:ESS11-subset", "Uniform Resource Name"),
        ("ESS11", "Local identifier"),
    ],
)
def test_identifier_classification_unchanged(ident, property_id):
    assert identifier_node(ident)["schema:propertyID"] == property_id


def test_ark_url_keeps_its_url():
    assert identifier_node("https://n2t.net/ark:/12345/abc")["schema:url"] == "https://n2t.net/ark:/12345/abc"


@pytest.mark.parametrize(
    "evil",
    [
        "/ark:/12345/" * 40_000 + " x",  # ~480 KB of ARK-like prefixes, then whitespace
        "ark:/12345/x " * 40_000 + "y",
        "ark:/" + "1" * 400_000 + " ",
    ],
)
def test_ark_detection_is_linear(evil):
    start = time.perf_counter()
    assert not is_ark(evil)
    identifier_node(evil)
    assert time.perf_counter() - start < 0.5


@pytest.mark.parametrize(
    "info",
    [
        {"identifier": "ark:/12345/" + "x" * 3000},
        {"record_id": "urn:" + "x" * 3000},
        {"description": "x" * 20_001},
        {"keywords": ["k"] * 201},
        {"keywords": ["x" * 501]},
        {"creators": [{"name": "x" * 501}]},
        {"publisher": {"name": "Sikt", "identifier": "x" * 2049}},
        {"funding": [{"funder": "x"}] * 101},
    ],
)
def test_oversized_dataset_info_is_rejected(client, info):  # noqa: F811
    fid = _upload(client).json()["file_id"]
    before = client.get(f"/api/files/{fid}/info").json()
    assert client.put(f"/api/files/{fid}/info", json=info).status_code == 422
    assert client.get(f"/api/files/{fid}/info").json() == before


def test_cdif_output_with_long_identifier_is_fast(client):  # noqa: F811
    fid = _upload(client).json()["file_id"]
    ident = "/ark:/12345/" * 170 + " x"  # just under the 2048-character limit
    assert client.put(f"/api/files/{fid}/info", json={"identifier": ident}).status_code == 200
    start = time.perf_counter()
    r = client.post(f"/api/files/{fid}/output", params={"format": "cdif"}, json={})
    assert r.status_code == 200
    assert time.perf_counter() - start < 10
