"""GitLab #12: names, labels and value labels are bounded on every path, and a build is
charged for its labelled codes and the bytes of data it reads."""

import pytest
from fastapi.testclient import TestClient

from ddicdi.api import admission, routes
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings
from ddicdi.data import DataTooLarge
from ddicdi.importers import readstat


@pytest.fixture()
def app(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return app


@pytest.fixture()
def client(app):
    return TestClient(app)


def _upload(client, body: bytes = b"a,b\n1,x\n2,y\n", name: str = "t.csv") -> str:
    r = client.post("/api/files", files={"file": (name, body)})
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


def test_csv_header_of_kilobytes_becomes_a_short_name(client):
    header = "q" * 5000
    fid = _upload(client, f"{header},b\n1,2\n".encode())
    info = client.get(f"/api/files/{fid}").json()
    names = [v["name"] for v in info["variables"]]
    assert all(len(n) <= settings.max_name_chars for n in names)
    assert len(info["variables"][0]["label"]) <= settings.max_label_chars


def test_rename_and_add_refuse_long_names(client):
    fid = _upload(client)
    long = "n" * (settings.max_name_chars + 1)
    assert client.patch(f"/api/files/{fid}/variables/a", json={"new_name": long}).status_code == 400
    assert client.post(f"/api/files/{fid}/variables", json={"name": long}).status_code == 400
    ok = "n" * settings.max_name_chars
    assert client.patch(f"/api/files/{fid}/variables/a", json={"new_name": ok}).status_code == 200


def test_labels_and_missing_ranges_are_bounded(client):
    fid = _upload(client)
    too_long = "l" * (settings.max_label_chars + 1)
    assert client.patch(f"/api/files/{fid}/variables/a", json={"label": too_long}).status_code == 400
    assert client.patch(f"/api/files/{fid}/variables/a", json={"value_labels": {"1": too_long}}).status_code == 400
    ranges = [{"lo": i} for i in range(settings.max_missing_ranges + 1)]
    assert client.patch(f"/api/files/{fid}/variables/a", json={"missing": ranges}).status_code == 400


def test_readstat_variables_over_the_limits_are_refused():
    meta = {"variables": [{"name": "v" * 100, "type": "Num"}]}
    with pytest.raises(ValueError, match="characters long"):
        readstat.metadata_from_readstat(meta, "x.sav", "spss")
    meta = {"variables": [{"name": "v", "type": "Num", "value_labels": {"x" * 2000: "a"}}]}
    with pytest.raises(ValueError, match="value-label code"):
        readstat.metadata_from_readstat(meta, "x.sav", "spss")


def test_build_cost_counts_codes_and_data_bytes(app, client):
    fid = _upload(client)
    dataset = app.state.store.load(fid)
    req = routes.OutputRequest(max_rows=0)
    base = routes._build_cost(dataset, req, "cdif")
    client.patch(f"/api/files/{fid}/variables/a", json={"value_labels": {str(i): "x" for i in range(100)}})
    dataset = app.state.store.load(fid)
    assert routes._build_cost(dataset, req, "cdif") == base + 100 * admission.CODE_COST
    all_rows = routes._build_cost(dataset, routes.OutputRequest(process_all_rows=True), "ddicdi")
    data = routes._data_bytes(dataset, 2)
    assert data == dataset.csv_path.stat().st_size  # all rows may read the whole file
    assert all_rows == base + 100 * admission.CODE_COST + 2 * 2 + data // admission.DATA_BYTES_PER_UNIT


def test_metadata_over_the_budget_is_413(app, client, monkeypatch):
    fid = _upload(client)
    client.patch(f"/api/files/{fid}/variables/a", json={"value_labels": {str(i): "x" for i in range(200)}})
    monkeypatch.setattr(settings, "max_output_cells", 150)
    r = client.post(f"/api/files/{fid}/output?format=cdif", json={"max_rows": 0})
    assert r.status_code == 413 and "value labels" in r.json()["detail"]


def test_build_reads_no_more_data_than_it_was_charged_for(app, client, monkeypatch):
    rows = "".join(f"{i},{'x' * 200}\n" for i in range(50))
    fid = _upload(client, ("a,b\n" + rows).encode())
    monkeypatch.setattr(settings, "max_output_data_bytes", 1000)
    r = client.post(f"/api/files/{fid}/output", json={"process_all_rows": True})
    assert r.status_code == 413 and "more data" in r.json()["detail"]
    monkeypatch.setattr(settings, "max_output_data_bytes", 1 << 20)
    assert client.post(f"/api/files/{fid}/output", json={"process_all_rows": True}).status_code == 200


def test_head_with_a_byte_limit_raises(app, client):
    fid = _upload(client, ("a,b\n" + "".join(f"{i},{'y' * 500}\n" for i in range(10))).encode())
    dataset = app.state.store.load(fid)
    with pytest.raises(DataTooLarge):
        dataset.head(10, max_bytes=1000)
    assert len(dataset.head(10, max_bytes=100_000)) == 10


def test_preview_keys_are_short(client):
    fid = _upload(client, ("," .join("k" * 3000 + str(i) for i in range(5)) + "\n" + ",".join("1" * 5) + "\n").encode())
    r = client.get(f"/api/files/{fid}?preview_rows=1000")
    assert r.status_code == 200
    assert all(len(k) <= settings.max_name_chars for row in r.json()["preview"] for k in row)
