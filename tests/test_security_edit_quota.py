"""Issue #2: edits cannot fill the work disk, and a failed rewrite leaves nothing behind."""

import os
import time

import pytest
from fastapi.testclient import TestClient

from ddicdi import editing
from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings

CSV = "id,name\n" + "".join(f"{i},n{i}\n" for i in range(200))


@pytest.fixture()
def store(tmp_path, qsv):
    return UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)


@pytest.fixture()
def client(store):
    app = create_app()
    app.state.store = store
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def fid(client):
    r = client.post("/api/files", files={"file": ("small.csv", CSV.encode())})
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


def _csv(store, fid):
    return store.root / fid / "data.csv"


def test_oversized_fill_value_is_rejected(client, fid, store):
    before = _csv(store, fid).read_bytes()
    r = client.post(
        f"/api/files/{fid}/variables",
        json={"name": "big", "fill": "constant", "fill_value": "x" * (settings.max_cell_chars + 1)},
    )
    assert r.status_code == 422
    assert _csv(store, fid).read_bytes() == before


def test_oversized_cell_is_rejected(client, fid):
    r = client.patch(f"/api/files/{fid}/rows/0", json={"values": {"name": "x" * (settings.max_cell_chars + 1)}})
    assert r.status_code == 422
    r = client.post(f"/api/files/{fid}/rows", json={"values": {"name": "x" * (settings.max_cell_chars + 1)}})
    assert r.status_code == 422


def test_editing_checks_cell_length_too(store, fid, monkeypatch):
    monkeypatch.setattr(settings, "max_cell_chars", 10)
    dataset = store.load(fid)
    with pytest.raises(editing.EditError):
        editing.add_variable(dataset, editing.NewVariable(name="c", fill="constant", fill_value="x" * 11))
    with pytest.raises(editing.EditError):
        editing.update_cells(dataset, 0, {"name": "x" * 11})
    with pytest.raises(editing.EditError):
        editing.append_row(dataset, {"name": "x" * 11})


def test_constant_fill_over_projected_size_is_refused(client, fid, store, monkeypatch):
    size = _csv(store, fid).stat().st_size
    monkeypatch.setattr(settings, "edit_max_csv_bytes", size + 1000)
    r = client.post(f"/api/files/{fid}/variables", json={"name": "c", "fill": "constant", "fill_value": "x" * 100})
    assert r.status_code == 400 and "storage limit" in r.json()["detail"]
    assert _csv(store, fid).stat().st_size == size
    assert not list((store.root / fid).glob("*.tmp"))


def test_repeated_copy_fills_stop_at_the_quota(client, fid, store, monkeypatch):
    limit = _csv(store, fid).stat().st_size * 3
    monkeypatch.setattr(settings, "edit_max_csv_bytes", limit)
    statuses = []
    for i in range(10):
        r = client.post(f"/api/files/{fid}/variables", json={"name": f"copy{i}", "fill": "copy", "fill_value": "name"})
        statuses.append(r.status_code)
        assert _csv(store, fid).stat().st_size <= limit
    assert 400 in statuses
    assert not list((store.root / fid).glob("*.tmp"))


def test_work_dir_quota_counts_other_uploads(client, fid, store, monkeypatch):
    (store.root / "other").mkdir()
    (store.root / "other" / "data.csv").write_bytes(b"x" * 50_000)
    monkeypatch.setattr(settings, "work_dir_max_bytes", 50_000 + 5_000)
    r = client.post(f"/api/files/{fid}/variables", json={"name": "c", "fill": "constant", "fill_value": "y" * 50})
    assert r.status_code == 400 and "storage limit" in r.json()["detail"]


def test_failed_rewrite_leaves_no_tmp_and_keeps_data(store, fid, monkeypatch):
    dataset = store.load(fid)
    before = dataset.csv_path.read_bytes()

    def failing(row, i):
        if i == 50:
            raise OSError(28, "No space left on device")
        return row

    with pytest.raises(OSError):
        editing._rewrite(dataset, failing, dataset.meta.column_names)
    assert dataset.csv_path.read_bytes() == before
    assert not list(dataset.csv_path.parent.glob("*.tmp"))


def test_disk_full_edit_is_a_507(client, fid, store, monkeypatch):
    real = editing._rewrite

    def full(dataset, transform, header):
        def boom(row, i):
            raise OSError(28, "No space left on device")

        return real(dataset, boom, header)

    monkeypatch.setattr(editing, "_rewrite", full)
    r = client.delete(f"/api/files/{fid}/rows/0")
    assert r.status_code == 507
    assert not list((store.root / fid).glob("*.tmp"))


def test_expired_uploads_are_removed_even_when_create_fails(store, monkeypatch):
    old = store.root / "expired"
    old.mkdir()
    (old / "data.csv").write_text("a\n1\n")
    past = time.time() - store.ttl - 10
    os.utime(old, (past, past))

    def no_space(*args, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("pathlib.Path.write_bytes", no_space)
    with pytest.raises(OSError):
        store.create("x.csv", b"a\n1\n")
    assert not old.exists()
