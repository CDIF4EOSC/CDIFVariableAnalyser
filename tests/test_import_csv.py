from pathlib import Path

from ddicdi.importers import import_file
from tests.conftest import original_file


def test_semicolon_csv(qsv, work_dir):
    ds = import_file(original_file("sample_data.csv"), work_dir, qsv)
    meta = ds.meta
    assert meta.file_format == "csv"
    assert meta.delimiter == ";"
    assert meta.number_rows == 10
    assert meta.column_names == ["id", "name", "age", "income", "education", "date_of_birth", "is_employed"]
    assert meta.var("age").storage_type == "numeric" and meta.var("age").measure == "scale"
    assert meta.var("name").storage_type == "string" and meta.var("name").measure == "nominal"
    assert meta.var("date_of_birth").storage_type == "datetime"
    assert meta.var("is_employed").storage_type == "boolean"
    # cached copy is comma separated
    assert (work_dir / "data.csv").read_text().splitlines()[0] == "id,name,age,income,education,date_of_birth,is_employed"
    assert ds.preview(1)[0]["name"] == "John Smith"


def test_comma_csv_written_locally(qsv, work_dir, tmp_path: Path):
    src = tmp_path / "t.csv"
    src.write_text("a,b\n1,x\n2.0,y\n")
    ds = import_file(src, work_dir, qsv)
    assert ds.meta.number_rows == 2
    assert [r[0] for r in ds.head(2)] == ["1", "2"]  # numeric column normalised


CRON3 = Path(__file__).resolve().parent.parent / "test-files" / "CRON3w6e01.csv"


def test_misleading_sniff_falls_back_to_headers_and_stats(qsv, work_dir):
    """A user-agent column full of semicolons makes qsv sniff pick ';' and report no header."""
    if not CRON3.exists():
        import pytest

        pytest.skip(f"{CRON3} not available")
    ds = import_file(CRON3, work_dir, qsv)
    meta = ds.meta
    assert meta.delimiter == ","
    assert meta.number_rows == 9585
    assert len(meta.variables) == 156
    assert meta.column_names[:5] == ["w6name", "w6edition", "w6proddate", "idno", "cntry"]
    assert meta.var("idno").storage_type == "numeric"
    assert meta.var("w6pspwght").storage_type == "numeric"
    assert meta.var("w6inwds").storage_type == "datetime"
    assert meta.var("w6uagent").storage_type == "string"


def test_header_heuristic():
    from ddicdi.importers.csv_reader import _looks_like_header

    assert _looks_like_header([["id", "name"], ["1", "x"]])
    assert not _looks_like_header([["1", "x"], ["2", "y"]])  # numeric first row
    assert not _looks_like_header([["id", "id"], ["1", "2"]])  # duplicate names
    assert not _looks_like_header([["id", ""], ["1", "2"]])  # empty name
    assert not _looks_like_header([])


def test_semicolons_inside_quoted_text_do_not_change_delimiter(qsv, work_dir, tmp_path: Path):
    src = tmp_path / "ua.csv"
    rows = ["id,ua,score"] + [f'{i},"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Gecko/{i}",{i * 1.5}' for i in range(1, 60)]
    src.write_text("\n".join(rows) + "\n")
    ds = import_file(src, work_dir, qsv)
    assert ds.meta.delimiter == ","
    assert ds.meta.column_names == ["id", "ua", "score"]
    assert ds.meta.number_rows == 59


def test_csv_format_from_profile():
    from ddicdi.importers.csv_reader import csv_format

    assert csv_format("numeric", {"type": "Integer", "min": "7", "max": "100"}) == "F3.0"
    assert csv_format("numeric", {"type": "Float", "min": "-1.5", "max": "12.25", "max_precision": 2}) == "F5.2"
    assert csv_format("string", {"type": "String", "max_length": 14}) == "A14"
    assert csv_format("string", {"type": "String", "max_length": 0}) == "A1"
    assert csv_format("datetime", {"type": "Date", "min": "2023-11-30", "max": "2024-01-02"}) == "SDATE10"
    assert csv_format("numeric", None) == "F8.2" and csv_format("string", None) == "A8"


def test_csv_widths_and_decimals(qsv, work_dir, tmp_path: Path):
    src = tmp_path / "t.csv"
    src.write_text("name,age,score,flag,when\nAnn,34,3.5,true,2024-01-02\nBobby,7,12.25,false,2023-11-30\n")
    meta = import_file(src, work_dir, qsv).meta
    assert meta.var("name").format == "A5"
    assert meta.var("age").format == "F2.0"
    assert meta.var("score").format == "F5.2"
    assert meta.var("flag").format == "A5"
    assert meta.var("when").format == "SDATE10"


def test_parse_format():
    from ddicdi.models import parse_format

    assert parse_format("F8.2") == (8, 2)
    assert parse_format("A20") == (20, None)
    assert parse_format("DATETIME23.2") == (23, 2)
    assert parse_format("%9.0g") == (9, 0)
    assert parse_format("%12s") == (12, None)
    assert parse_format("BEST12.") == (12, None)
    assert parse_format("$20.") == (20, None)
    assert parse_format("%tdCCYY") == (None, None)
    assert parse_format("") == (None, None)
