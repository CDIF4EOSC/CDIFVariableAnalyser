from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ddicdi.config import settings
from ddicdi.importers import import_file
from ddicdi.qsv import Qsv

ROOT = Path(__file__).resolve().parent.parent
ESS11_SAV = ROOT / "test-files" / "ESS11-subset.sav"
FIXTURES = Path(__file__).parent / "fixtures"
ORIGINAL_FILES = Path("/Users/beb/dev/DDICDI_generator/files")


def original_file(name: str) -> Path:
    """A sample file from the original app; skips the test when unavailable."""
    p = ORIGINAL_FILES / name
    if not p.exists():
        pytest.skip(f"{p} not available")
    return p


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch):
    """Ignore a DDI_API_KEY from a local .env; test_api_key sets its own."""
    monkeypatch.setattr(settings, "api_key", None)


@pytest.fixture(scope="session")
def qsv() -> Qsv:
    try:
        return Qsv()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


@pytest.fixture()
def sentinel_qsv(qsv) -> Qsv:
    """A qsv build that keeps user-missing codes (``readstat --sentinels-as``, qsv#4667)."""
    if not qsv.supports_sentinels:
        pytest.skip(f"{qsv.version()} has no readstat --sentinels-as")
    return qsv


@pytest.fixture(scope="session")
def ess11(qsv, tmp_path_factory):
    return import_file(ESS11_SAV, tmp_path_factory.mktemp("ess11"), qsv)


@pytest.fixture()
def work_dir(tmp_path) -> Path:
    d = tmp_path / "work"
    d.mkdir()
    yield d
    shutil.rmtree(d, ignore_errors=True)
