"""Statistics in the JSON-LD output: a StatisticsCollection per variable, Statistics and
CategoryStatistics over the code lists' categories."""

import json

import pytest

from ddicdi.cdi.jsonld import GenerateOptions, build_document, generate_complete_json_ld
from ddicdi.cdi.statistics import PERCENTAGE, STATISTIC_NAMES, VALID_CASES
from ddicdi.importers import import_file
from ddicdi.models import MissingRange


@pytest.fixture(scope="module")
def doc(ess11):
    return build_document(ess11, options=GenerateOptions(max_rows=2, include_statistics=True))


STATISTICS = ("Statistics", "CategoryStatistics")


def _by_type(doc, t):
    types = STATISTICS if t == "Statistics" else (t,)
    return [e for e in doc["DDICDIModels"] if e["@type"] in types]


def _collections(doc):
    return [e for e in doc["DDICDIModels"] if e["@type"] == "StatisticsCollection"]


def test_off_by_default(ess11):
    """Only the statistics are optional; the code lists carry Category and Notation anyway."""
    plain = build_document(ess11, options=GenerateOptions(max_rows=2))
    assert not _by_type(plain, "Statistics") and not _collections(plain)
    assert not [e for e in plain["DDICDIModels"] if e["@type"] == "InstanceVariable" and "isDescribedBy" in e]


def test_summary_statistic_shape(doc):
    mean = next(e for e in _by_type(doc, "Statistics") if e["@id"] == "#statistics-ppltrst-mean")
    assert mean["@type"] == "Statistics"
    assert mean["typeOfStatistic"] == {"@type": "ControlledVocabularyEntry", "entryValue": "mean"}
    assert mean["has_StatisticsCollection"] == "#statisticsCollection-ppltrst"
    assert "for" not in mean  # a summary statistic is about the variable, not a category
    assert "hasWeight" not in mean  # unweighted run
    (stat,) = mean["statistic"]
    assert stat["@type"] == "Statistic"
    assert isinstance(stat["content"], (int, float)) and not isinstance(stat["content"], bool)
    assert stat["isWeighted"] is False
    assert stat["computationBase"] == "ValidOnly"


def test_every_variable_reports_its_valid_cases(ess11, doc):
    reported = {
        e["has_StatisticsCollection"] for e in _by_type(doc, "Statistics") if e["@id"].endswith(f"-{VALID_CASES}")
    }
    assert reported == {f"#statisticsCollection-{v}" for v in ess11.meta.column_names}


def test_one_collection_per_described_variable(ess11, doc):
    """The variable ``isDescribedBy`` its collection, and the bundles point back at it."""
    collections = {e["@id"] for e in _collections(doc)}
    assert collections == {f"#statisticsCollection-{v}" for v in ess11.meta.column_names}
    described = {
        e["@id"]: e["isDescribedBy"] for e in doc["DDICDIModels"] if e["@type"] == "InstanceVariable"
    }
    assert set(described.values()) == collections
    assert all(iv == coll.replace("#statisticsCollection-", "#instanceVariable-") for iv, coll in described.items())
    assert {e["has_StatisticsCollection"] for e in _by_type(doc, "Statistics")} == collections
    for coll in _collections(doc):
        assert "hasWeight" not in coll


def test_category_statistics_reference_a_category(doc):
    cats = {e["@id"] for e in _by_type(doc, "Category")}
    per_category = _by_type(doc, "CategoryStatistics")
    assert per_category
    assert all("for" in e for e in per_category)
    assert not [e for e in _by_type(doc, "Statistics") if e["@type"] == "Statistics" and "for" in e]
    assert {e["for"] for e in per_category} <= cats
    # each category a frequency was computed for carries both a count and a percentage
    for c in {e["for"] for e in per_category}:
        kinds = {e["typeOfStatistic"]["entryValue"] for e in per_category if e["for"] == c}
        assert kinds == {"frequency", "percentage"}


def test_a_labelled_code_is_not_duplicated(doc):
    """The statistic points at the Category the code list already declared."""
    ids = [e["@id"] for e in _by_type(doc, "Category")]
    assert len(ids) == len(set(ids))
    code = next(e for e in _by_type(doc, "Code") if e["@id"] == "#code-ppltrst-0")
    stat = next(e for e in _by_type(doc, "CategoryStatistics") if e["@id"] == "#categoryStatistics-ppltrst-0-frequency")
    assert stat["for"] == code["denotes"] == "#category-ppltrst-0"


def test_values_without_a_label_get_their_own_category(doc):
    """proddate has no value labels, so its frequencies bring their own Category."""
    cat = next(e for e in _by_type(doc, "Category") if e["@id"] == "#category-proddate-20.06.2024")
    assert "displayLabel" not in cat
    assert not [e for e in _by_type(doc, "Code") if e["@id"].startswith("#code-proddate-")]
    assert next(e for e in _by_type(doc, "Notation") if e["@id"] == "#notation-proddate-20.06.2024")


def test_categories_are_notated(doc):
    ppltrst = next(e for e in _by_type(doc, "Category") if e["@id"] == "#category-ppltrst-0")
    assert ppltrst["name"] == {"@type": "ObjectName", "name": "0"}
    assert ppltrst["displayLabel"]["languageSpecificString"]["content"] == "You can't be too careful"

    notation = next(e for e in _by_type(doc, "Notation") if e["@id"] == "#notation-ppltrst-0")
    assert notation["content"] == {"@type": "TypedString", "content": "0"}
    assert notation["represents"] == ppltrst["@id"]
    # the SHACL requires one; no Category may be left without
    assert {e["represents"] for e in _by_type(doc, "Notation")} == {e["@id"] for e in _by_type(doc, "Category")}


def test_context_stays_a_plain_reference(doc):
    """Nothing in the statistics needs a prefix of its own."""
    assert doc["@context"].startswith("https://ddi-cdi.github.io/m2t-ng/DDI-CDI_1-1beta/")


def test_sentinel_categories_are_kept(qsv, tmp_path, work_dir):
    """A declared missing code that is in the data gets a frequency like any other.

    A readstat import keeps them too (qsv readstat --sentinels-embedded); see
    test_stats.test_category_labels_and_normalization for ESS11's 77/88/99.
    """
    csv = work_dir / "s.csv"
    csv.write_text("a\n1\n1\n2\n99\n")
    ds = import_file(csv, tmp_path / "out", qsv)
    ds.meta.var("a").missing_ranges = [MissingRange(99, 99)]
    ds.meta.var("a").value_labels = {"1": "yes", "2": "no", "99": "refusal"}
    doc = build_document(ds, options=GenerateOptions(max_rows=0, include_statistics=True))
    refusal = next(e for e in _by_type(doc, "Category") if e["@id"] == "#category-a-99")
    assert refusal["displayLabel"]["languageSpecificString"]["content"] == "refusal"
    count = next(e for e in _by_type(doc, "CategoryStatistics") if e["@id"] == "#categoryStatistics-a-99-frequency")
    assert count["statistic"][0]["content"] == 1


def test_dates_and_text_modes_are_skipped(doc):
    """``Statistic.content`` is xsd:double, so a string mode has nowhere to go."""
    for e in _by_type(doc, "Statistics"):
        for s in e["statistic"]:
            assert isinstance(s["content"], (int, float))
    proddate = [e["typeOfStatistic"]["entryValue"] for e in _by_type(doc, "Statistics")
                if e["has_StatisticsCollection"] == "#statisticsCollection-proddate" and "for" not in e]
    assert "mode" not in proddate  # "20.06.2024" is not a number
    assert VALID_CASES in proddate


def test_weighted_run_marks_the_statistics(ess11):
    doc = build_document(
        ess11, options=GenerateOptions(max_rows=0, include_statistics=True, statistics_weight="dweight")
    )
    mean = next(e for e in _by_type(doc, "Statistics") if e["@id"] == "#statistics-ppltrst-mean")
    assert mean["statistic"][0]["isWeighted"] is True
    assert mean["hasWeight"] == "#instanceVariable-dweight"
    # counting the non-empty cells is not affected by the weight
    valid = next(e for e in _by_type(doc, "Statistics") if e["@id"] == f"#statistics-ppltrst-{VALID_CASES}")
    assert valid["statistic"][0]["isWeighted"] is False
    assert "hasWeight" not in valid
    # the collection names the weight the run was made with
    coll = next(e for e in _collections(doc) if e["@id"] == "#statisticsCollection-ppltrst")
    assert coll["hasWeight"] == "#instanceVariable-dweight"
    # qsv drops the weight column itself from a weighted run: no statistics, no collection
    assert not [e for e in _collections(doc) if e["@id"] == "#statisticsCollection-dweight"]
    dweight = next(e for e in doc["DDICDIModels"] if e["@id"] == "#instanceVariable-dweight")
    assert "isDescribedBy" not in dweight


def test_unknown_weight_is_rejected(ess11):
    with pytest.raises(ValueError, match="Unknown weight"):
        build_document(ess11, options=GenerateOptions(max_rows=0, include_statistics=True, statistics_weight="nope"))


def test_moments_leave_out_the_missing_codes_that_are_in_the_data(qsv, tmp_path, work_dir):
    """A CSV upload keeps the declared missing codes in the cells; the moments still leave them out."""
    csv = work_dir / "x.csv"
    csv.write_text("a\n1\n2\n99\n")
    ds = import_file(csv, tmp_path / "out", qsv)
    ds.meta.var("a").missing_ranges = [MissingRange(99, 99)]
    doc = build_document(ds, options=GenerateOptions(max_rows=0, include_statistics=True))
    mean = next(e for e in _by_type(doc, "Statistics") if e["@id"] == "#statistics-a-mean")
    assert mean["statistic"][0]["computationBase"] == "ValidOnly"
    assert mean["statistic"][0]["content"] == 1.5


def test_percentages_are_kept_as_qsv_reports_them(ess11):
    text = generate_complete_json_ld(ess11, max_rows=0, include_statistics=True)
    doc = json.loads(text)
    pct = [
        e for e in doc["DDICDIModels"]
        if e["@type"] == "CategoryStatistics"
        and e.get("typeOfStatistic", {}).get("entryValue") == PERCENTAGE
        and e["has_StatisticsCollection"] == "#statisticsCollection-cntry"
    ]
    assert round(sum(e["statistic"][0]["content"] for e in pct)) == 100


# -- selecting which statistics are emitted -------------------------------------------


def _kinds(doc) -> set[str]:
    return {e["typeOfStatistic"]["entryValue"] for e in _by_type(doc, "Statistics")}


def test_every_emitted_kind_is_in_the_vocabulary(doc):
    """The selection box offers STATISTIC_NAMES, so nothing may be emitted outside it."""
    assert _kinds(doc) <= set(STATISTIC_NAMES)


def test_a_selection_keeps_only_what_it_names(ess11):
    doc = build_document(
        ess11,
        options=GenerateOptions(max_rows=0, include_statistics=True, statistics_include=["mean", "median"]),
    )
    assert _kinds(doc) == {"mean", "median"}


def test_a_selection_without_frequencies_skips_the_frequency_pass(ess11, monkeypatch):
    called = False

    def spy(*args, **kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("ddicdi.cdi.statistics.category_stats_many", spy)
    build_document(
        ess11, options=GenerateOptions(max_rows=0, include_statistics=True, statistics_include=["mean"])
    )
    assert not called
    build_document(
        ess11, options=GenerateOptions(max_rows=0, include_statistics=True, statistics_include=["percentage"])
    )
    assert called


def test_an_empty_selection_emits_no_statistics(ess11):
    doc = build_document(ess11, options=GenerateOptions(max_rows=0, include_statistics=True, statistics_include=[]))
    assert not _by_type(doc, "Statistics") and not _collections(doc)


def test_a_variable_without_statistics_has_no_collection(ess11):
    """A ``mean`` selection leaves the text columns with nothing to collect."""
    doc = build_document(
        ess11, options=GenerateOptions(max_rows=0, include_statistics=True, statistics_include=["mean"])
    )
    collections = {e["@id"] for e in _collections(doc)}
    assert "#statisticsCollection-ppltrst" in collections
    assert "#statisticsCollection-cntry" not in collections
    cntry = next(e for e in doc["DDICDIModels"] if e["@id"] == "#instanceVariable-cntry")
    assert "isDescribedBy" not in cntry


def test_a_frequency_only_selection_still_carries_its_categories(ess11):
    """The statistics point at Category nodes, so those have to come along."""
    doc = build_document(
        ess11, options=GenerateOptions(max_rows=0, include_statistics=True, statistics_include=["frequency"])
    )
    per_category = _by_type(doc, "CategoryStatistics")
    assert per_category
    assert {e["for"] for e in per_category} <= {e["@id"] for e in _by_type(doc, "Category")}
