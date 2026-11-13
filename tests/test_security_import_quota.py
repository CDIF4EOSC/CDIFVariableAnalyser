"""Security #10: imports respect the work-dir quota; a full work dir still allows
edits that do not grow an upload."""

import io

import pytest
from fastapi.testclient import TestClient

from ddicdi.api.main import create_app
from ddicdi.api.store import StorageFull, UploadStore
from ddicdi.config import settings
from ddicdi.editing import work_dir_usage


def _csv(rows: int) -> bytes:
    return b"name,n\n" + b"".join(b"row%d,%d\n" % (i, i) for i in range(rows))


@pytest.fixture()
def store(tmp_path, qsv):
    return UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)


@pytest.fixture()
def client(store):
    app = create_app()
    app.state.store = store
    with TestClient(app) as c:
        yield c


def _fill(store, size: int) -> None:
    """Another user's upload taking ``size`` bytes."""
    (store.root / "other").mkdir(exist_ok=True)
    (store.root / "other" / "data.csv").write_bytes(b"x" * size)


def _upload(client, rows: int = 100):
    return client.post("/api/files", files={"file": ("d.csv", io.BytesIO(_csv(rows)))})


def test_import_refused_when_the_work_dir_is_full(client, store, monkeypatch):
    _fill(store, 50_000)
    monkeypatch.setattr(settings, "work_dir_max_bytes", 50_500)
    r = _upload(client)
    assert r.status_code == 507 and "storage" in r.json()["detail"]
    assert [p.name for p in store.root.iterdir()] == ["other"]
    r = client.post("/api/convert", files={"file": ("d.csv", io.BytesIO(_csv(100)))})
    assert r.status_code == 507
    assert [p.name for p in store.root.iterdir()] == ["other"]


def test_import_refused_when_the_expanded_data_does_not_fit(store, monkeypatch):
    """The source fits; source plus data.csv does not. Nothing is left behind."""
    content = _csv(2_000)
    monkeypatch.setattr(settings, "work_dir_max_bytes", len(content) + 1_000)
    with pytest.raises(StorageFull):
        store.create("d.csv", content)
    assert list(store.root.iterdir()) == []


def test_repeated_imports_stop_at_the_quota(client, store, monkeypatch):
    monkeypatch.setattr(settings, "work_dir_max_bytes", 60_000)
    codes = [_upload(client, 500).status_code for _ in range(20)]
    assert codes[0] == 200 and 507 in codes
    assert codes == sorted(codes)  # once refused, refused
    assert work_dir_usage(store.root) <= 60_000


@pytest.fixture()
def over_quota(client, store, monkeypatch):
    """An upload of this user while another upload has pushed the work dir far over quota."""
    fid = _upload(client).json()["file_id"]
    _fill(store, 1_000_000)
    monkeypatch.setattr(settings, "work_dir_max_bytes", 100_000)
    return fid


def test_non_growing_edits_work_over_quota(client, store, over_quota):
    fid = over_quota
    r = client.patch(f"/api/files/{fid}/rows/3", json={"values": {"name": "row9"}})
    assert r.status_code == 200, r.text
    r = client.patch(f"/api/files/{fid}/variables/name", json={"new_name": "nm"})
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/files/{fid}/rows/0")
    assert r.status_code == 200, r.text
    r = client.delete(f"/api/files/{fid}/variables/n")
    assert r.status_code == 200, r.text


def test_growing_edits_are_refused_over_quota(client, store, over_quota):
    fid = over_quota
    size = (store.root / fid / "data.csv").stat().st_size
    r = client.post(f"/api/files/{fid}/rows", json={"values": {"name": "new"}})
    assert r.status_code == 400 and "storage limit" in r.json()["detail"]
    r = client.post(f"/api/files/{fid}/variables", json={"name": "c", "fill": "constant", "fill_value": "y"})
    assert r.status_code == 400
    r = client.patch(f"/api/files/{fid}/rows/3", json={"values": {"name": "z" * 500}})
    assert r.status_code == 400
    assert (store.root / fid / "data.csv").stat().st_size == size
