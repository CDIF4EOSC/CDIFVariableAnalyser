import json

import pytest
from fastapi.testclient import TestClient

from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings
from tests.conftest import ESS11_SAV, original_file


@pytest.fixture()
def client(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    with TestClient(app) as c:
        yield c


def _upload(client, path=ESS11_SAV, **params):
    with path.open("rb") as fh:
        return client.post("/api/files", files={"file": (path.name, fh)}, params=params)


def test_health_and_info(client):
    h = client.get("/api/health").json()
    assert h["status"] == "healthy" and h["qsv"]
    info = client.get("/api/info").json()
    assert ".sav" in info["supported_extensions"] and info["output_format"] == "application/ld+json"


def test_upload_metadata_preview_generate_delete(client):
    r = _upload(client)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["filename"] == "ESS11-subset.sav" and j["file_format"] == "spss"
    assert j["number_rows"] == 2420 and j["number_variables"] == 13
    assert len(j["preview"]) == 5 and j["preview"][0]["idno"] == "50004"
    ppltrst = next(v for v in j["variables"] if v["name"] == "ppltrst")
    assert ppltrst["missing"] == [{"lo": "77", "hi": "77"}, {"lo": "88", "hi": "88"}, {"lo": "99", "hi": "99"}]
    assert ppltrst["default_role"] == "measure"
    fid = j["file_id"]

    assert client.get(f"/api/files/{fid}").json()["number_rows"] == 2420
    p = client.get(f"/api/files/{fid}/preview", params={"rows": 2}).json()
    assert p["columns"][0] == "name" and len(p["rows"]) == 2 and p["total_rows"] == 2420

    r = client.post(f"/api/files/{fid}/generate", json={"roles": {"idno": "identifier"}, "max_rows": 2})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="ESS11-subset_DDICDI.jsonld"'
    doc = json.loads(r.content)
    assert any(x["@type"] == "PrimaryKey" for x in doc["DDICDIModels"])
    assert sum(1 for x in doc["DDICDIModels"] if x["@type"] == "InstanceValue") == 26

    assert client.delete(f"/api/files/{fid}").status_code == 204
    assert client.get(f"/api/files/{fid}").status_code == 404


def test_output_with_a_statistics_selection(client):
    fid = _upload(client).json()["file_id"]
    body = {"max_rows": 0, "include_statistics": True, "statistics_include": ["mean", "validCases"]}
    doc = client.post(f"/api/files/{fid}/output", json=body).json()
    kinds = {
        e["typeOfStatistic"]["entryValue"]
        for e in doc["DDICDIModels"]
        if e["@type"] in ("Statistics", "CategoryStatistics")
    }
    assert kinds == {"mean", "validCases"}


def test_an_unknown_statistic_is_rejected(client):
    fid = _upload(client).json()["file_id"]
    r = client.post(f"/api/files/{fid}/output", json={"include_statistics": True, "statistics_include": ["nope"]})
    assert r.status_code == 422
    assert "nope" in json.dumps(r.json())
    assert "mean" in client.get("/api/info").json()["statistics"]


def test_bad_role_and_unknown_file(client):
    fid = _upload(client).json()["file_id"]
    r = client.post(f"/api/files/{fid}/generate", json={"roles": {"nope": "measure"}})
    assert r.status_code == 400
    r = client.post(f"/api/files/{fid}/generate", json={"roles": {"idno": "primary"}})
    assert r.status_code == 400
    assert client.post("/api/files/deadbeef/generate", json={}).status_code == 404


def test_unsupported_extension(client, tmp_path):
    p = tmp_path / "x.xlsx"
    p.write_bytes(b"nope")
    assert _upload(client, p).status_code == 400


def test_convert_one_shot_compatible(client):
    with ESS11_SAV.open("rb") as fh:
        r = client.post(
            "/api/convert",
            files={"file": (ESS11_SAV.name, fh)},
            data={"max_rows": "0", "variable_roles": json.dumps({"idno": "identifier"})},
        )
    assert r.status_code == 200
    doc = json.loads(r.content)
    assert not any(x["@type"] == "InstanceValue" for x in doc["DDICDIModels"])
    assert any(x["@type"] == "PrimaryKey" for x in doc["DDICDIModels"])
    # nothing is left behind
    assert list(client.app.state.store.root.iterdir()) == []


def test_csv_upload(client):
    r = _upload(client, original_file("sample_data.csv"))
    assert r.status_code == 200, r.text
    assert r.json()["delimiter"] == ";" and r.json()["number_rows"] == 10


def test_parquet_upload(client, qsv, tmp_path):
    src = tmp_path / "survey.parquet"
    qsv.run("sqlp", "SKIP_INPUT", "SELECT * FROM (SELECT 1 AS id, 'a' AS s UNION ALL SELECT 2, 'b') ORDER BY id", "--format", "parquet", "-o", str(src))
    r = _upload(client, src)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["file_format"] == "parquet" and j["number_rows"] == 2 and j["preview"][1]["s"] == "b"
    r = client.post(f"/api/files/{j['file_id']}/generate", json={"max_rows": 2})
    assert r.status_code == 200
    assert any(x["@type"] == "StructuredDataSet" for x in json.loads(r.content)["DDICDIModels"])


def test_api_key(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    assert _upload(client).status_code == 401
    with ESS11_SAV.open("rb") as fh:
        r = client.post("/api/files", files={"file": (ESS11_SAV.name, fh)}, headers={"X-API-Key": "secret"})
    assert r.status_code == 200
