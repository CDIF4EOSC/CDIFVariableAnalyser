from pathlib import Path

import pytest

from ddicdi.qsv import Qsv, QsvError
from tests.conftest import ESS11_SAV


def test_version_and_readstat_available(qsv: Qsv):
    assert qsv.version().startswith("qsv ")
    assert qsv.has_command("readstat")


def test_readstat_metadata_shape(qsv: Qsv):
    meta = qsv.readstat_metadata(ESS11_SAV)
    assert meta["row_count"] == 2420
    assert meta["encoding"] == "UTF-8"
    assert [v["name"] for v in meta["variables"]][:3] == ["name", "essround", "edition"]
    ppltrst = next(v for v in meta["variables"] if v["name"] == "ppltrst")
    assert ppltrst["missing_doubles"] == [77.0, 88.0, 99.0]
    assert ppltrst["value_labels"]["77"] == "Refusal"


def test_readstat_to_csv_count_headers_slice(qsv: Qsv, tmp_path: Path):
    out = tmp_path / "data.csv"
    qsv.readstat_to_csv(ESS11_SAV, out)
    assert qsv.count(out) == 2420
    assert qsv.headers(out)[:2] == ["name", "essround"]
    rows = qsv.slice(out, 0, 2)
    assert len(rows) == 2
    assert rows[0][0] == "ESS11e01"
    assert qsv.slice(out, 0, 0) == []


def test_error_is_raised(qsv: Qsv, tmp_path: Path):
    with pytest.raises(QsvError):
        qsv.count(tmp_path / "does-not-exist.csv")
