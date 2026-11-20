"""GitLab #8: element ids of long, hyphen-rich codes cost linear time; codes are bounded."""

import time

import pytest
from fastapi.testclient import TestClient

from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.cdi.ids import IdMap
from ddicdi.config import settings
from ddicdi.models import DatasetMeta, Variable


def _meta(*names: str) -> DatasetMeta:
    return DatasetMeta(variables=[Variable(name=n) for n in names], number_rows=0, datafile="x.csv", file_format="csv")


def test_stable_key_finds_the_variable_name():
    ids = IdMap(_meta("age", "age_group", "x.y"))
    assert ids._stable_key("code-age-1")[1] == "age"
    assert ids._stable_key("code-age_group-1-2")[1] == "age_group"
    assert ids._stable_key("dataPoint-7-x.y")[1] == "x.y"
    assert ids._stable_key("code-unknown-1") == ("code-unknown-1", None)


def test_stable_key_prefers_the_longest_name_with_hyphens():
    ids = IdMap(_meta("a", "a-b"))  # names read back from a document may hold "-"
    assert ids._stable_key("code-a-b-1")[1] == "a-b"
    assert ids._stable_key("code-a-c")[1] == "a"


def test_stable_key_is_linear_in_the_code_length():
    ids = IdMap(_meta("v"))
    short, long = "-" * 2_000, "-" * 200_000

    def timed(code: str) -> float:
        t0 = time.perf_counter()
        for kind in ("code", "codePosition", "category", "notation"):
            ids._stable_key(f"{kind}-v-{code}")
        return time.perf_counter() - t0

    timed(short)
    # 100x the length: quadratic would be ~10,000x; allow generous noise for linear.
    assert timed(long) < max(timed(short) * 1000, 0.5)


def test_stable_key_is_cached():
    ids = IdMap(_meta("v"))
    fragment = "code-v-" + "-" * 1000
    assert ids._stable_key(fragment) is ids._stable_key(fragment)


@pytest.fixture()
def client(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return TestClient(app)


def _upload(client) -> str:
    r = client.post("/api/files", files={"file": ("t.csv", b"a,b\n1,x\n2,y\n")})
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


def test_edit_refuses_an_overlong_value_label_code(client):
    fid = _upload(client)
    code = "-" * (settings.max_code_chars + 1)
    r = client.patch(f"/api/files/{fid}/variables/a", json={"value_labels": {code: "x"}})
    assert r.status_code == 400
    assert "value-label code" in r.json()["detail"]
    ok = client.patch(f"/api/files/{fid}/variables/a", json={"value_labels": {"-" * settings.max_code_chars: "x"}})
    assert ok.status_code == 200


def test_edit_refuses_too_many_value_labels(client, monkeypatch):
    monkeypatch.setattr(settings, "max_value_labels", 3)
    fid = _upload(client)
    r = client.patch(f"/api/files/{fid}/variables/a", json={"value_labels": {str(i): "x" for i in range(4)}})
    assert r.status_code == 400 and "value labels" in r.json()["detail"]
    r = client.post(f"/api/files/{fid}/variables", json={"name": "c", "value_labels": {str(i): "x" for i in range(4)}})
    assert r.status_code == 400


def test_document_with_a_maximum_length_hyphen_code_builds_quickly(client):
    fid = _upload(client)
    code = "-" * settings.max_code_chars
    assert client.patch(f"/api/files/{fid}/variables/b", json={"value_labels": {code: "dashes"}}).status_code == 200
    for fmt in ("ddicdi", "cdif"):
        t0 = time.perf_counter()
        r = client.post(f"/api/files/{fid}/output?format={fmt}", json={"max_rows": 2})
        assert r.status_code == 200, r.text
        assert time.perf_counter() - t0 < 5


def test_overlong_data_values_get_no_category_statistics(client, monkeypatch):
    monkeypatch.setattr(settings, "max_code_chars", 5)
    r = client.post("/api/files", files={"file": ("t.csv", b"a,b\n1,short\n2,muchlonger\n3,short\n")})
    fid = r.json()["file_id"]
    r = client.post(f"/api/files/{fid}/output", json={"max_rows": 0, "include_statistics": True})
    assert r.status_code == 200, r.text
    assert "muchlonger" not in r.text
