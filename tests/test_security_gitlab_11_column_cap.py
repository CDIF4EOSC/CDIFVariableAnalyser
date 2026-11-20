"""GitLab #11: the column cap is checked before per-column work, and qsv metadata
output read into the app is bounded."""

import pytest

from ddicdi.config import settings
from ddicdi.importers import readstat
from ddicdi.importers.csv_reader import import_csv
from ddicdi.qsv import Qsv, QsvError


def test_wide_csv_is_refused_before_profiles(tmp_path, qsv, monkeypatch):
    monkeypatch.setattr(settings, "max_variables", 100)
    calls = []
    monkeypatch.setattr(Qsv, "column_profiles", lambda self, p: calls.append("profiles") or [])
    monkeypatch.setattr(Qsv, "normalize_csv", lambda self, *a, **k: calls.append("normalize"))
    src = tmp_path / "wide.csv"
    src.write_text(",".join(f"c{i}" for i in range(1000)) + "\n" + ",".join(["1"] * 1000) + "\n")
    with pytest.raises(ValueError, match="1000 variables; the limit is 100"):
        import_csv(src, tmp_path / "data.csv", qsv)
    assert calls == []


def test_readstat_count_is_checked_before_variables_are_built(monkeypatch):
    monkeypatch.setattr(settings, "max_variables", 3)
    built = []
    monkeypatch.setattr(readstat, "_spss_variable", lambda v: built.append(v))
    meta_json = {"variables": [{"name": f"v{i}"} for i in range(10)]}
    with pytest.raises(ValueError, match="limit is 3"):
        readstat.metadata_from_readstat(meta_json, "x.sav", "spss")
    assert built == []


def test_qsv_metadata_output_is_bounded(tmp_path, qsv, monkeypatch):
    monkeypatch.setattr(settings, "qsv_max_output_bytes", 1000)
    src = tmp_path / "wide.csv"
    src.write_text(",".join(f"column_{i}" for i in range(500)) + "\n" + ",".join(["1"] * 500) + "\n")
    with pytest.raises(QsvError, match="more than 1000 bytes"):
        qsv.headers(src)
    monkeypatch.setattr(settings, "qsv_max_output_bytes", 1 << 20)
    assert len(qsv.headers(src)) == 500


def test_bounded_run_reports_qsv_errors(tmp_path, qsv):
    with pytest.raises(QsvError, match="failed"):
        qsv.run("headers", str(tmp_path / "missing.csv"), max_output=1000)


def test_upload_over_the_cap_is_a_400_and_leaves_nothing(tmp_path, qsv, monkeypatch):
    from fastapi.testclient import TestClient

    from ddicdi.api.main import create_app
    from ddicdi.api.store import UploadStore

    monkeypatch.setattr(settings, "max_variables", 10)
    app = create_app()
    root = tmp_path / "uploads"
    app.state.store = UploadStore(root, ttl_seconds=3600, qsv=qsv)
    body = (",".join(f"c{i}" for i in range(50)) + "\n" + ",".join(["1"] * 50) + "\n").encode()
    r = TestClient(app).post("/api/files", files={"file": ("w.csv", body)})
    assert r.status_code == 400 and "limit is 10" in r.json()["detail"]
    assert list(root.iterdir()) == []
