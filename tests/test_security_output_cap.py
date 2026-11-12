"""Issue #3: generate, output and convert refuse documents over ``max_output_cells``."""

import pytest
from fastapi.testclient import TestClient

from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings

ROWS, COLS = 2000, 3


@pytest.fixture()
def many_rows_csv(tmp_path):
    p = tmp_path / "many.csv"
    lines = ["a,b,c"] + [f"{i},{i % 7},x{i % 3}" for i in range(ROWS)]
    p.write_text("\n".join(lines) + "\n")
    return p


@pytest.fixture()
def client(tmp_path, qsv, monkeypatch):
    monkeypatch.setattr(settings, "max_output_cells", 1000)
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    with TestClient(app) as c:
        yield c


def _upload(client, path):
    with path.open("rb") as fh:
        r = client.post("/api/files", files={"file": (path.name, fh)})
    assert r.status_code == 200, r.text
    assert r.json()["number_rows"] == ROWS
    return r.json()["file_id"]


@pytest.mark.parametrize("endpoint", ["generate", "output"])
@pytest.mark.parametrize("fmt", ["ddicdi", "cdif"])
@pytest.mark.parametrize(
    "body", [{"process_all_rows": True}, {"max_rows": 10_000_000}, {"max_rows": 334}], ids=["all", "huge", "just-over"]
)
def test_too_many_cells_refused(client, many_rows_csv, endpoint, fmt, body):
    fid = _upload(client, many_rows_csv)
    r = client.post(f"/api/files/{fid}/{endpoint}", params={"format": fmt}, json=body)
    if fmt == "cdif":
        # CDIF carries no data rows, so the row count is irrelevant there.
        assert r.status_code == 200, r.text
        return
    assert r.status_code == 413, r.text
    assert "limit is 1,000" in r.json()["detail"] and "333 rows" in r.json()["detail"]


@pytest.mark.parametrize("endpoint", ["generate", "output"])
def test_within_limit_still_works(client, many_rows_csv, endpoint):
    fid = _upload(client, many_rows_csv)
    for body in ({"max_rows": 333}, {"max_rows": 0}, {"max_rows": 5}):
        r = client.post(f"/api/files/{fid}/{endpoint}", json=body)
        assert r.status_code == 200, r.text


def test_convert_refused_and_cleaned_up(client, many_rows_csv, tmp_path):
    with many_rows_csv.open("rb") as fh:
        r = client.post(
            "/api/convert",
            files={"file": (many_rows_csv.name, fh)},
            data={"process_all_rows": "true"},
        )
    assert r.status_code == 413, r.text
    assert not any((tmp_path / "uploads").iterdir())  # the one-shot upload is removed
    with many_rows_csv.open("rb") as fh:
        r = client.post("/api/convert", files={"file": (many_rows_csv.name, fh)}, data={"max_rows": "5"})
    assert r.status_code == 200, r.text


def test_limit_off(client, many_rows_csv, monkeypatch):
    monkeypatch.setattr(settings, "max_output_cells", 0)
    fid = _upload(client, many_rows_csv)
    r = client.post(f"/api/files/{fid}/output", json={"process_all_rows": True})
    assert r.status_code == 200, r.text
