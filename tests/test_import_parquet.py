import json
from pathlib import Path

import pytest

from ddicdi.cdi.jsonld import generate_complete_json_ld
from ddicdi.importers import import_file

# UNION ALL parts can come back in either order, hence the ORDER BY.
SAMPLE_SQL = (
    "SELECT * FROM (SELECT CAST(1 AS BIGINT) AS id, 'Oslo' AS city, 3.25 AS score, CAST('2024-01-02' AS DATE) AS born,"
    " STRPTIME('2024-01-02 03:04:05', '%Y-%m-%d %H:%M:%S') AS seen, CAST(1.5 AS DECIMAL(10,2)) AS amount,"
    " CAST(7 AS INT) AS q1"
    " UNION ALL SELECT 2, 'Bergen', 10.5, CAST('1990-12-31' AS DATE),"
    " STRPTIME('2024-02-03 00:00:00', '%Y-%m-%d %H:%M:%S'), CAST(22.75 AS DECIMAL(10,2)), NULL) ORDER BY id"
)


def _write_parquet(qsv, path: Path, sql: str) -> Path:
    qsv.run("sqlp", "SKIP_INPUT", sql, "--format", "parquet", "-o", str(path))
    return path


@pytest.fixture()
def sample(qsv, tmp_path) -> Path:
    return _write_parquet(qsv, tmp_path / "sample.parquet", SAMPLE_SQL)


def test_parquet_import(qsv, work_dir, sample):
    ds = import_file(sample, work_dir, qsv)
    meta = ds.meta
    assert meta.file_format == "parquet"
    assert meta.datafile == "sample.parquet"
    assert meta.number_rows == 2
    assert meta.column_names == ["id", "city", "score", "born", "seen", "amount", "q1"]
    assert meta.encoding is None and meta.delimiter is None  # binary, not delimited text
    assert meta.sentinels_in_data
    for name in ("id", "score", "amount", "q1"):
        assert meta.var(name).storage_type == "numeric" and meta.var(name).measure == "scale", name
    assert meta.var("city").storage_type == "string"
    assert meta.var("born").storage_type == "datetime" and meta.var("seen").storage_type == "datetime"
    assert meta.var("amount").format == "F5.2"
    # the values are kept as stored: codes stay numbers, a null is an empty cell
    rows = ds.preview(2)
    assert rows[0]["city"] == "Oslo" and rows[0]["q1"] == "7" and rows[1]["q1"] == ""
    assert (work_dir / "data.csv").read_text().splitlines()[0] == "id,city,score,born,seen,amount,q1"


def test_parquet_is_a_structured_data_set(qsv, work_dir, sample):
    ds = import_file(sample, work_dir, qsv)
    doc = json.loads(generate_complete_json_ld(ds, spssfile="sample.parquet", max_rows=2))
    models = doc["DDICDIModels"]
    pds = next(x for x in models if x["@id"] == "#structuredDataSet")
    assert pds["@type"] == "StructuredDataSet"
    assert pds["name"]["name"] == "sample.parquet" and pds["recordCount"] == 2
    assert "encoding" not in pds and "delimiter" not in pds
    loc = next(x for x in models if x["@id"] == "#locatorMapping-city")
    assert loc["@type"] == "LocatorMapping" and loc["locator"] == "city"


def test_nested_parquet_columns_are_refused(qsv, work_dir, tmp_path):
    src = _write_parquet(qsv, tmp_path / "nested.parquet", "SELECT 1 AS id, [1, 2] AS items")
    with pytest.raises(ValueError, match="nested columns"):
        import_file(src, work_dir, qsv)
