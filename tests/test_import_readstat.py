import csv
import json
import math
from collections import Counter

from ddicdi.importers import import_file
from ddicdi.importers.readstat import spss_format_string
from ddicdi.models import DatasetMeta
from tests.conftest import ESS11_SAV, FIXTURES, original_file


def test_ess11_metadata_matches_pyreadstat_baseline(ess11):
    """Baseline recorded once from pyreadstat (tests/fixtures/ess11_meta_baseline.json)."""
    baseline = json.loads((FIXTURES / "ess11_meta_baseline.json").read_text())
    meta = ess11.meta
    assert meta.number_rows == baseline["number_rows"]
    assert meta.column_names == baseline["column_names"]
    for v in meta.variables:
        b = baseline["variables"][v.name]
        assert v.label == b["label"], v.name
        assert v.format == b["format"], v.name
        assert v.storage_type == b["readstat_type"], v.name
        assert v.measure == b["measure"], v.name
        assert v.value_labels == b["value_labels"], v.name
        assert [r.to_dict() for r in v.missing_ranges] == b["missing_ranges"], v.name


def test_ess11_data_access(ess11):
    row = ess11.preview(1)[0]
    assert row["essround"] == "11"  # 11.0 normalised
    assert row["edition"] == "1.0"  # string variable, untouched
    assert row["dweight"] == "0.9958686232566833"
    assert row["hinctnta"] == "9"
    assert len(ess11.head(5)) == 5
    assert sum(1 for _ in ess11.iter_rows()) == 2420
    chunks = list(ess11.iter_chunks(1000))
    assert [start for start, _ in chunks] == [0, 1000, 2000]
    assert len(chunks[-1][1]) == 420


def test_meta_roundtrip(ess11):
    d = ess11.meta.to_dict()
    again = DatasetMeta.from_dict(json.loads(json.dumps(d)))
    assert again == ess11.meta


def test_meta_roundtrip_with_unit_and_concepts(ess11):
    import copy

    from ddicdi.models import Concept

    meta = copy.deepcopy(ess11.meta)
    v = meta.var("ppltrst")
    v.unit_of_measure = "http://publications.europa.eu/resource/authority/measurement-unit/HUR"
    v.concepts = [Concept(uri="https://elsst.cessda.eu/id/6/abc", pref_label="TRUST")]
    v.functions = ["Weight"]
    again = DatasetMeta.from_dict(json.loads(json.dumps(meta.to_dict())))
    assert again == meta and again.var("ppltrst").concepts[0].pref_label == "TRUST"
    # meta.json written before these fields existed still loads
    d = ess11.meta.to_dict()
    for var in d["variables"]:
        var.pop("unit_of_measure")
        var.pop("concepts")
        var.pop("functions")
    assert DatasetMeta.from_dict(d) == ess11.meta


def test_spss_format_strings():
    assert spss_format_string(5, 2, 0) == "F2.0"
    assert spss_format_string(5, 3, 2) == "F3.2"
    assert spss_format_string(1, 8, 0) == "A8"
    assert spss_format_string(22, 23, 2) == "DATETIME23.2"
    assert spss_format_string(25, 12, 0) == "DTIME12"


def test_nes1948_sav_missing_ranges(qsv, work_dir):
    ds = import_file(original_file("NES1948.sav"), work_dir, qsv)
    v = ds.meta.var("v480005")
    assert ds.meta.number_rows == 662
    assert ds.meta.encoding == "windows-1252"
    assert [(r.lo, r.hi) for r in v.missing_ranges] == [(9.0, math.inf), (0.0, 0.0)]
    assert v.is_missing_code("9") and v.is_missing_code("12") and not v.is_missing_code("1")
    assert v.sentinel_codes() == ["0", "9"]
    assert v.substantive_codes() == ["1", "2", "3", "4", "5", "6", "7", "8"]


def test_nes1948_dta(qsv, work_dir):
    ds = import_file(original_file("NES1948.dta"), work_dir, qsv)
    assert ds.meta.file_format == "stata"
    assert ds.meta.number_rows == 662
    v = ds.meta.var("V480005")
    assert v.storage_type in ("int8", "int16", "int32", "float", "double")
    assert v.format.startswith("%")
    assert v.measure == "unknown"
    assert ds.preview(1)[0]["V480005"] == "1"


def test_cronos_dates(qsv, work_dir):
    ds = import_file(original_file("CRON3W1e01_4.sav"), work_dir, qsv)
    assert ds.meta.number_rows == 9884
    assert ds.meta.var("w1inwds").format == "DATETIME23.2"
    assert ds.meta.var("w1edur").format == "DTIME12"
    assert ds.meta.var("mnactic").missing_ranges[0].to_dict() == {"lo": "66", "hi": "99"}
    row = ds.preview(1)[0]
    assert row["w1inwds"].startswith("2024-")


def test_user_missing_codes_are_kept(sentinel_qsv, work_dir):
    """CRON3 declares 999, 66/99 and 7777/8888/9999; qsv keeps them in the cells."""
    ds = import_file(original_file("CRON3W1e01_4.sav"), work_dir, sentinel_qsv)
    assert ds.meta.sentinels_in_data
    freq: dict[str, Counter] = {"age": Counter(), "w1hq5": Counter(), "yrbrn": Counter()}
    names = ds.meta.column_names
    for row in ds.iter_rows():
        for name, counts in freq.items():
            counts[row[names.index(name)]] += 1
    assert freq["age"]["999"] == 25
    assert (freq["w1hq5"]["66"], freq["w1hq5"]["99"]) == (9323, 236)
    assert (freq["yrbrn"]["7777"], freq["yrbrn"]["8888"], freq["yrbrn"]["9999"]) == (8, 5, 12)
    assert ds.meta.var("w1hq5").is_missing_code("66")


def test_stata_user_missing_stay_empty(qsv, work_dir):
    """qsv refuses --sentinels-as for Stata (qsv#4627), so the import leaves it off."""
    ds = import_file(original_file("NES1948.dta"), work_dir, qsv)
    assert ds.meta.sentinels_in_data is False


def test_kept_codes_are_spelled_like_the_other_values(sentinel_qsv, work_dir):
    """qsv writes 10.0 for a value but 77 for an embedded sentinel; data.csv gets 77.0."""
    ds = import_file(ESS11_SAV, work_dir, sentinel_qsv)
    with ds.csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        col = next(reader).index("hinctnta")
        raw = Counter(row[col] for row in reader)
    assert (raw["77.0"], raw["88.0"], raw["99.0"]) == (140, 110, 1)
    assert not {"77", "88", "99"} & set(raw)
    assert all("." in cell for cell in raw if cell)
