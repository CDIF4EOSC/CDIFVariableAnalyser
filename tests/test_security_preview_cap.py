"""Security #9: row previews are bounded by cells and bytes; uploads by variable count."""

import io

import pytest
from fastapi.testclient import TestClient

from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings

COLS, ROWS = 200, 300


def _wide(cols: int = COLS, rows: int = ROWS, cell: str = "x") -> bytes:
    head = ",".join(f"v{i}" for i in range(cols))
    return (head + "\n" + "".join(",".join(f"{cell}{r}" for _ in range(cols)) + "\n" for r in range(rows))).encode()


@pytest.fixture()
def store(tmp_path, qsv):
    return UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)


@pytest.fixture()
def client(store):
    app = create_app()
    app.state.store = store
    with TestClient(app) as c:
        yield c


def _post(client, data: bytes, **params) -> dict:
    r = client.post("/api/files", params=params, files={"file": ("wide.csv", io.BytesIO(data))})
    assert r.status_code == 200, r.text
    return r.json()


def _upload(client, data: bytes, **params) -> str:
    return _post(client, data, **params)["file_id"]


def test_preview_rows_are_capped_by_cells(client, monkeypatch):
    monkeypatch.setattr(settings, "max_preview_cells", 2_000)  # 10 rows of 200 columns
    fid = _upload(client, _wide(), preview_rows=1000)
    for params in ({"rows": 10000}, {"rows": 10000, "offset": 50}):
        page = client.get(f"/api/files/{fid}/preview", params=params).json()
        assert len(page["rows"]) == 10
        assert page["total_rows"] == ROWS
    page = client.get(f"/api/files/{fid}/preview", params={"rows": 10000, "offset": 50}).json()
    assert page["rows"][0][0] == "x50"
    info = client.get(f"/api/files/{fid}", params={"preview_rows": 1000}).json()
    assert len(info["preview"]) == 10


def test_upload_preview_is_capped(client, monkeypatch):
    monkeypatch.setattr(settings, "max_preview_cells", 2_000)
    info = _post(client, _wide(), preview_rows=1000)
    assert len(info["preview"]) == 10


def test_preview_bytes_are_capped(client, monkeypatch):
    """Long cells: the byte budget stops reading early; only whole records come back."""
    long_cell = "y" * 5_000
    fid = _upload(client, _wide(cols=4, rows=200, cell=long_cell))
    monkeypatch.setattr(settings, "max_preview_bytes", 100_000)  # ~5 records of 20 KB
    page = client.get(f"/api/files/{fid}/preview", params={"rows": 200}).json()
    assert 1 <= len(page["rows"]) <= 5
    assert all(len(r) == 4 and all(c.startswith(long_cell) for c in r) for r in page["rows"])
    page = client.get(f"/api/files/{fid}/preview", params={"rows": 200, "offset": 100}).json()
    assert 1 <= len(page["rows"]) <= 5 and page["rows"][0][0] == f"{long_cell}100"


def test_small_preview_unchanged(client):
    fid = _upload(client, _wide(cols=3, rows=20))
    page = client.get(f"/api/files/{fid}/preview", params={"rows": 100}).json()
    assert len(page["rows"]) == 20


def test_slice_byte_cap_on_qsv(qsv, tmp_path):
    p = tmp_path / "d.csv"
    p.write_bytes(_wide(cols=2, rows=1000))
    full = qsv.slice(p, 0, 1000)
    assert len(full) == 1000
    capped = qsv.slice(p, 0, 1000, max_bytes=500)
    assert 0 < len(capped) < 1000
    assert capped == full[: len(capped)]


def test_upload_with_too_many_variables_is_refused(client, store, monkeypatch):
    monkeypatch.setattr(settings, "max_variables", 50)
    r = client.post("/api/files", files={"file": ("wide.csv", io.BytesIO(_wide(cols=51, rows=3)))})
    assert r.status_code == 400 and "limit is 50" in r.text
    assert list(store.root.iterdir()) == []
    r = client.post("/api/convert", files={"file": ("wide.csv", io.BytesIO(_wide(cols=51, rows=3)))})
    assert r.status_code == 400
    assert list(store.root.iterdir()) == []


def test_add_variable_respects_max_variables(client, monkeypatch):
    fid = _upload(client, _wide(cols=5, rows=3))
    monkeypatch.setattr(settings, "max_variables", 6)
    r = client.post(f"/api/files/{fid}/variables", json={"name": "extra"})
    assert r.status_code == 201, r.text
    r = client.post(f"/api/files/{fid}/variables", json={"name": "one_too_many"})
    assert r.status_code == 400 and "maximum of 6" in r.text
