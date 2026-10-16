"""Statistics computed with ``qsv stats`` / ``qsv frequency``.

The expected numbers come from ESS11-subset.sav and double as a regression guard
on qsv's missing-value handling (dathere/qsv#4625, #4667): ``hinctnta``'s 77/88/99
codes are kept in data.csv, so they show up as 251 sentinel counts in the frequencies,
and are blanked in the valid-cases copy, so they are left out of the mean.
"""

from __future__ import annotations

import copy
import shutil

import pytest

from ddicdi import editing, stats as stats_mod
from ddicdi.data import Dataset


@pytest.fixture()
def ess11_copy(ess11, tmp_path, qsv) -> Dataset:
    """A private copy of the ESS11 CSV, so cache tests don't disturb the session fixture."""
    if not ess11.meta.sentinels_in_data:
        pytest.skip(f"{qsv.version()} writes user-missing codes as empty cells")
    csv_path = tmp_path / "data.csv"
    shutil.copy(ess11.csv_path, csv_path)
    return Dataset(ess11.meta, csv_path, qsv)


# -- the qsv wrappers -------------------------------------------------------------


def test_qsv_stats_jsonl_shape(qsv, ess11_copy):
    valid_csv, _ = stats_mod.valid_cases_csv(ess11_copy)
    rows = qsv.stats(valid_csv)
    by_name = {r["field"]: r for r in rows}
    assert len(rows) == 13

    hinctnta = by_name["hinctnta"]
    assert hinctnta["nullcount"] == 251  # 77/88/99 blanked in the valid-cases copy
    assert hinctnta["type"] == "Float"
    assert float(hinctnta["mean"]) == pytest.approx(6.1867, abs=1e-4)
    assert float(hinctnta["q2_median"]) == 7.0

    ppltrst = by_name["ppltrst"]
    assert ppltrst["nullcount"] == 0
    assert float(ppltrst["mean"]) == pytest.approx(5.1897, abs=1e-4)
    assert ppltrst["cardinality"] == 11

    cntry = by_name["cntry"]
    assert cntry["type"] == "String"
    assert "avg_length" in cntry and "mean" not in cntry


def test_qsv_frequency_json_shape(qsv, ess11_copy):
    names = ess11_copy.meta.column_names
    select = [names.index("hinctnta") + 1, names.index("cntry") + 1]
    out = qsv.frequency(ess11_copy.csv_path, select=select, limit=25)

    assert out["rowcount"] == 2420
    fields = {f["field"]: f for f in out["fields"]}

    hinctnta = fields["hinctnta"]
    assert hinctnta["nullcount"] == 0  # the 251 user-missing cells hold 77/88/99
    assert hinctnta["cardinality"] == 13  # --no-nulls keeps the NULL bucket out
    assert len(hinctnta["frequencies"]) == 13
    top = hinctnta["frequencies"][0]
    assert set(top) == {"value", "count", "percentage", "rank"}
    assert top == {"value": "10.0", "count": 327, "percentage": pytest.approx(13.512, abs=1e-3), "rank": 1.0}
    assert sum(e["count"] for e in hinctnta["frequencies"]) == 2420

    assert fields["cntry"]["frequencies"] == [
        {"value": "DE", "count": 2420, "percentage": 100.0, "rank": 1.0}
    ]


def test_qsv_frequency_truncation_is_rank_zero(qsv, ess11_copy):
    names = ess11_copy.meta.column_names
    out = qsv.frequency(ess11_copy.csv_path, select=[names.index("hinctnta") + 1], limit=5)
    freqs = out["fields"][0]["frequencies"]
    assert len(freqs) == 6
    other = freqs[-1]
    assert other["rank"] == 0 and other["value"] == "Other (8)" and other["count"] == 1116


# -- classification ----------------------------------------------------------------


def _by_name(ds) -> dict:
    return {v.name: v for v in ds.variables}


def test_classification(ess11_copy):
    got = _by_name(stats_mod.summary_stats(ess11_copy))

    # Labelled 0-10 scale: categorical AND numeric -- it gets both a frequency
    # table and a mean.
    ppltrst = got["ppltrst"]
    assert ppltrst.kind == "categorical" and ppltrst.numeric and ppltrst.has_categories

    assert got["cntry"].kind == "categorical"  # labelled, constant string

    idno = got["idno"]  # 2420 distinct values in 2420 rows
    assert idno.kind == "numeric" and not idno.has_categories

    psu = got["psu"]  # cardinality 500
    assert psu.kind == "numeric" and not psu.has_categories


def test_sentinel_only_labels_are_not_a_codelist(ess11_copy):
    """A variable that only labels its missing codes is not categorical."""
    from ddicdi.models import MissingRange

    var = ess11_copy.meta.var("idno")
    var.value_labels = {"999999": "Not available"}
    var.missing_ranges = [MissingRange(999999.0, 999999.0)]
    assert var.substantive_codes() == []
    assert stats_mod.classify(var, "Float", 2420, 2420) == "numeric"

    # ... but one substantive code is enough to make it a codelist.
    var.value_labels["1"] = "First"
    assert stats_mod.classify(var, "Float", 2420, 2420) == "categorical"


def test_summary_values_and_missing(ess11_copy):
    ds = stats_mod.summary_stats(ess11_copy)
    assert ds.total_rows == 2420
    assert ds.excludes_sentinels is True and ds.degraded is False
    got = _by_name(ds)

    for v in ds.variables:
        assert v.valid_n + v.missing_n == 2420, v.name

    hinctnta = got["hinctnta"]
    assert (hinctnta.valid_n, hinctnta.missing_n) == (2169, 251)
    assert hinctnta.sentinel_codes == ["77", "88", "99"]
    # qsv stats counts the empty cells as a distinct value; we report 10, the same
    # number the frequency table shows.
    assert hinctnta.cardinality == 10
    assert got["ppltrst"].cardinality == 11  # no missings, so nothing to subtract
    stats = {s.name: s.value for s in hinctnta.stats}
    assert stats["mean"] == "6.1867"
    assert stats["median"] == "7" and stats["firstQuartile"] == "4" and stats["thirdQuartile"] == "9"
    assert stats["standardDeviation"] == "2.7646"

    ppltrst = {s.name: s.value for s in got["ppltrst"].stats}
    assert ppltrst["mean"] == "5.1897" and ppltrst["minimum"] == "0" and ppltrst["maximum"] == "10"

    # String columns get length statistics and no moments.
    name = {s.name: s.value for s in got["name"].stats}
    assert "mean" not in name and name["averageLength"] == "8"


def test_category_labels_and_normalization(ess11_copy):
    cats = stats_mod.category_stats(ess11_copy, "hinctnta", limit=25)
    assert (cats.valid_n, cats.missing_n) == (2420, 0)
    assert cats.cardinality == 13 and not cats.truncated and not cats.all_unique

    top = cats.categories[0]
    assert top.code == "10"  # "10.0" normalised, so value_labels match
    assert top.count == 327 and top.label is not None and not top.sentinel

    # qsv keeps the user-missing codes, so they are counted as sentinel categories.
    sentinels = {c.code: c.count for c in cats.categories if c.sentinel}
    assert sentinels == {"77": 140, "88": 110, "99": 1}
    assert cats.valid_n_substantive == 2169


def test_category_sort_by_code(ess11_copy):
    cats = stats_mod.category_stats(ess11_copy, "hinctnta", limit=25, sort="code")
    assert [c.code for c in cats.categories] == [str(i) for i in range(1, 11)] + ["77", "88", "99"]


def test_category_truncation(ess11_copy):
    cats = stats_mod.category_stats(ess11_copy, "hinctnta", limit=5)
    assert cats.truncated and cats.other_count == 1116
    assert len(cats.categories) == 5
    assert all(c.rank > 0 for c in cats.categories)


def test_all_unique_column_is_cheap(ess11_copy):
    cats = stats_mod.category_stats(ess11_copy, "idno", limit=25)
    assert cats.all_unique or cats.truncated
    assert len(cats.categories) <= 25


# -- weights -----------------------------------------------------------------------


def test_weight_candidates_and_resolution(ess11_copy):
    meta = ess11_copy.meta
    for name in ("dweight", "pweight"):
        meta.var(name).functions = ["Weight"]
    assert stats_mod.weight_candidates(meta) == ["dweight", "pweight"]
    assert stats_mod.resolve_weight(meta, "auto") == "dweight"
    assert stats_mod.resolve_weight(meta, None) is None
    with pytest.raises(ValueError):
        stats_mod.resolve_weight(meta, "nope")
    with pytest.raises(ValueError):
        stats_mod.resolve_weight(meta, "cntry")  # not numeric


def test_weighted_stats_differ(ess11_copy):
    unweighted = _by_name(stats_mod.summary_stats(ess11_copy))
    weighted_ds = stats_mod.summary_stats(ess11_copy, weight="dweight")
    weighted = _by_name(weighted_ds)

    assert weighted_ds.weight == "dweight"
    assert weighted["ppltrst"].stats != unweighted["ppltrst"].stats

    # qsv drops the weight column from its output; we keep it visible.
    assert weighted["dweight"].is_weight and weighted["dweight"].stats == []


# -- caching and invalidation ------------------------------------------------------


def test_cache_is_written_reused_and_invalidated(ess11_copy):
    cache = ess11_copy.csv_path.with_name("data.valid.stats.csv")
    assert not cache.exists()

    first = stats_mod.summary_stats(ess11_copy)
    assert cache.exists()
    assert stats_mod.summary_stats(ess11_copy).variables == first.variables

    # An edit rewrites data.csv, so qsv must recompute rather than serve the cache.
    for i in range(20):
        editing.update_cells(ess11_copy, i, {"ppltrst": "10"})
    after = _by_name(stats_mod.summary_stats(ess11_copy))
    before = _by_name(first)
    assert after["ppltrst"].stats != before["ppltrst"].stats


def test_changed_missing_values_recompute_the_moments(ess11_copy):
    ds = Dataset(copy.deepcopy(ess11_copy.meta), ess11_copy.csv_path, ess11_copy.qsv)
    mean = lambda: {s.name: s.value for s in _by_name(stats_mod.summary_stats(ds))["hinctnta"].stats}["mean"]
    assert mean() == "6.1867"  # 77/88/99 left out
    ds.meta.var("hinctnta").missing_ranges = []
    assert float(mean()) > 10  # now averaged in


# -- edges -------------------------------------------------------------------------


def test_parse_cardinality_handles_qsv_sentinels():
    assert stats_mod._parse_cardinality(11) == (11, False)
    assert stats_mod._parse_cardinality(">=100000") == (None, True)
    assert stats_mod._parse_cardinality(None) == (None, False)
    assert stats_mod._parse_cardinality("") == (None, False)


def test_empty_and_header_only_csv(qsv, work_dir):
    from ddicdi.importers import import_file

    src = work_dir / "tiny.csv"
    src.write_text("a,b\n1,\n2,\n3,\n")
    ds = import_file(src, work_dir, qsv)
    got = _by_name(stats_mod.summary_stats(ds))
    assert got["b"].kind == "empty" and got["b"].valid_n == 0 and got["b"].stats == []
    assert got["a"].valid_n == 3


def test_zero_row_csv(qsv, work_dir):
    """A header-only CSV: qsv reports NULL columns, nothing divides by valid_n."""
    from ddicdi.models import DatasetMeta, Variable

    csv_path = work_dir / "data.csv"
    csv_path.write_text("x,y\n")
    meta = DatasetMeta(
        variables=[Variable(name="x"), Variable(name="y")],
        number_rows=0,
        datafile="headers.csv",
        file_format="csv",
    )
    ds = stats_mod.summary_stats(Dataset(meta, csv_path, qsv))
    assert [v.kind for v in ds.variables] == ["empty", "empty"]
    assert all(v.valid_n == 0 and v.stats == [] for v in ds.variables)


def test_csv_upload_keeps_its_missing_codes(qsv, work_dir):
    from ddicdi.importers import import_file
    from ddicdi.models import MissingRange

    src = work_dir / "survey.csv"
    src.write_text("q1\n1\n2\n2\n99\n99\n")
    ds = import_file(src, work_dir, qsv)
    ds.meta.var("q1").missing_ranges = [MissingRange(99.0, 99.0)]

    summary = stats_mod.summary_stats(ds)
    assert summary.excludes_sentinels is True
    q1 = {s.name: s.value for s in _by_name(summary)["q1"].stats}
    assert q1["mean"] == "1.6667" and q1["maximum"] == "2"  # 99 is not averaged in
    cats = stats_mod.category_stats(ds, "q1", limit=25)
    sentinels = [c for c in cats.categories if c.sentinel]
    assert [c.code for c in sentinels] == ["99"] and sentinels[0].count == 2
    assert cats.valid_n == 5 and cats.valid_n_substantive == 3


# -- API -----------------------------------------------------------------------------


@pytest.fixture()
def client(tmp_path, qsv):
    from fastapi.testclient import TestClient

    from ddicdi.api.main import create_app
    from ddicdi.api.store import UploadStore

    app = create_app()
    app.state.store = UploadStore(tmp_path / "uploads", ttl_seconds=3600, qsv=qsv)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def uploaded(client):
    from tests.conftest import ESS11_SAV

    with ESS11_SAV.open("rb") as fh:
        r = client.post("/api/files", files={"file": (ESS11_SAV.name, fh)})
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


def test_statistics_endpoint(client, uploaded):
    r = client.get(f"/api/files/{uploaded}/statistics")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["file_id"] == uploaded and body["total_rows"] == 2420
    assert body["excludes_sentinels"] is True and body["degraded"] is False
    assert body["weight"] is None and body["weight_candidates"] == []

    got = {v["name"]: v for v in body["variables"]}
    assert len(got) == 13
    hinctnta = got["hinctnta"]
    assert hinctnta["label"] and hinctnta["kind"] == "categorical" and hinctnta["numeric"] is True
    assert (hinctnta["valid_n"], hinctnta["missing_n"]) == (2169, 251)
    assert hinctnta["sentinel_codes"] == ["77", "88", "99"]
    assert {"name": "mean", "value": "6.1867"} in hinctnta["stats"]
    assert got["cntry"]["numeric"] is False
    assert "mean" not in {s["name"] for s in got["cntry"]["stats"]}

    # A repeat call hits qsv's cache and returns the same numbers.
    again = client.get(f"/api/files/{uploaded}/statistics").json()
    assert again["variables"] == body["variables"]


def test_statistics_weighted_endpoint(client, uploaded):
    client.patch(f"/api/files/{uploaded}/variables/dweight", json={"functions": ["Weight"]})
    body = client.get(f"/api/files/{uploaded}/statistics").json()
    assert body["weight_candidates"] == ["dweight"]

    weighted = client.get(f"/api/files/{uploaded}/statistics", params={"weight": "dweight"}).json()
    assert weighted["weight"] == "dweight"
    got = {v["name"]: v for v in weighted["variables"]}
    assert got["dweight"]["is_weight"] is True and got["dweight"]["stats"] == []
    assert got["ppltrst"]["stats"] != {v["name"]: v for v in body["variables"]}["ppltrst"]["stats"]


def test_categories_endpoint(client, uploaded, sentinel_qsv):
    r = client.get(f"/api/files/{uploaded}/statistics/hinctnta/categories")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cardinality"] == 13 and body["missing_n"] == 0
    assert body["valid_n_substantive"] == 2169
    assert body["categories"][0]["code"] == "10" and body["categories"][0]["count"] == 327
    assert body["categories"][0]["label"]

    by_code = client.get(
        f"/api/files/{uploaded}/statistics/hinctnta/categories", params={"sort": "code"}
    ).json()
    assert [c["code"] for c in by_code["categories"]] == [str(i) for i in range(1, 11)] + ["77", "88", "99"]


def test_statistics_errors(client, uploaded):
    assert client.get("/api/files/deadbeef/statistics").status_code == 404
    assert client.get(f"/api/files/{uploaded}/statistics", params={"weight": "nope"}).status_code == 400
    assert client.get(f"/api/files/{uploaded}/statistics/nope/categories").status_code == 404


def test_statistics_do_not_change_the_document(client, uploaded):
    body = {"max_rows": 5}
    before = client.post(f"/api/files/{uploaded}/output", json=body).content
    client.get(f"/api/files/{uploaded}/statistics")
    client.get(f"/api/files/{uploaded}/statistics/hinctnta/categories")
    assert client.post(f"/api/files/{uploaded}/output", json=body).content == before


def test_output_with_statistics(client, uploaded):
    body = {"max_rows": 0, "include_statistics": True}
    doc = client.post(f"/api/files/{uploaded}/output", json=body).json()
    assert {"StatisticsCollection", "Statistics", "CategoryStatistics"} <= {e["@type"] for e in doc["DDICDIModels"]}

    # the code lists are there either way; only the statistics are optional
    plain = client.post(f"/api/files/{uploaded}/output", json={"max_rows": 0}).json()
    types = {e["@type"] for e in plain["DDICDIModels"]}
    assert "Statistics" not in types and {"CodeList", "Code", "Category", "Notation"} <= types


def test_download_with_statistics(client, uploaded):
    r = client.post(
        f"/api/files/{uploaded}/generate",
        json={"max_rows": 0, "include_statistics": True, "statistics_weight": "dweight"},
    )
    assert r.status_code == 200, r.text
    assert b"StatisticsCollection" in r.content and b'"hasWeight": "#instanceVariable-dweight"' in r.content


def test_output_statistics_weight_is_validated(client, uploaded):
    r = client.post(
        f"/api/files/{uploaded}/output",
        json={"max_rows": 0, "include_statistics": True, "statistics_weight": "nope"},
    )
    assert r.status_code == 400
