"""Security #1: imports are time- and size-bounded and do not block the event loop."""

import asyncio
import io
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from ddicdi.api.main import create_app
from ddicdi.api.store import UploadStore
from ddicdi.config import settings
from ddicdi.qsv import QsvError
from tests.conftest import ESS11_SAV


@pytest.fixture()
def app(tmp_path, qsv):
    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    return app


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def _uploads(app) -> list:
    return list(app.state.store.root.iterdir())


def _csv(rows: int) -> bytes:
    return b"a,b\n" + b"".join(b"%d,xxxxxxxxxx\n" % i for i in range(rows))


def test_qsv_call_times_out(qsv, monkeypatch):
    monkeypatch.setattr(settings, "qsv_timeout", 0.001)
    with pytest.raises(QsvError, match="timed out"):
        qsv.run("--version")


def test_explicit_timeout_still_wins(qsv, monkeypatch):
    monkeypatch.setattr(settings, "qsv_timeout", 0.001)
    assert qsv.run("--version", timeout=30)


def test_qsv_output_is_capped(qsv, tmp_path, monkeypatch):
    src = tmp_path / "big.csv"
    src.write_bytes(_csv(20_000))
    monkeypatch.setattr(settings, "import_max_bytes", 10_000)
    with pytest.raises(QsvError, match="larger than the limit"):
        qsv.normalize_csv(src, tmp_path / "out.csv")


def test_import_over_the_size_limit_is_rejected_and_leaves_nothing(app, client, monkeypatch):
    monkeypatch.setattr(settings, "import_max_bytes", 10_000)
    r = client.post("/api/files", files={"file": ("big.csv", io.BytesIO(_csv(20_000)))})
    assert r.status_code == 400 and "larger than the limit" in r.text
    assert _uploads(app) == []
    # one-shot convert as well
    r = client.post("/api/convert", files={"file": ("big.csv", io.BytesIO(_csv(20_000)))})
    assert r.status_code == 400
    assert _uploads(app) == []


def test_import_timeout_is_rejected_and_leaves_nothing(app, client, monkeypatch):
    monkeypatch.setattr(settings, "qsv_timeout", 0.001)
    with ESS11_SAV.open("rb") as fh:
        r = client.post("/api/files", files={"file": (ESS11_SAV.name, fh)})
    assert r.status_code == 400 and "timed out" in r.text
    assert _uploads(app) == []


def test_oversized_upload_is_413(app, client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_bytes", 1000)
    r = client.post("/api/files", files={"file": ("big.csv", io.BytesIO(_csv(1000)))})
    assert r.status_code == 413
    r = client.post("/api/convert", files={"file": ("big.csv", io.BytesIO(_csv(1000)))})
    assert r.status_code == 413
    assert _uploads(app) == []


def test_small_upload_still_works(client):
    r = client.post("/api/files", files={"file": ("small.csv", io.BytesIO(_csv(10)))})
    assert r.status_code == 200, r.text
    assert r.json()["number_rows"] == 10


def test_health_is_served_during_a_slow_import(app, monkeypatch):
    def slow_create(filename, content):
        time.sleep(1.5)
        raise ValueError("slow import")

    monkeypatch.setattr(app.state.store, "create", slow_create)

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            upload = asyncio.create_task(
                ac.post("/api/files", files={"file": ("x.csv", b"a\n1\n")})
            )
            await asyncio.sleep(0.2)
            t0 = time.monotonic()
            health = await ac.get("/api/health")
            elapsed = time.monotonic() - t0
            assert not upload.done()
            r = await upload
            return health, elapsed, r

    health, elapsed, r = asyncio.run(scenario())
    assert health.status_code == 200
    assert elapsed < 1.0
    assert r.status_code == 400
