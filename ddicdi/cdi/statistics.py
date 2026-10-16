"""Statistics in the DDI-CDI output: ``StatisticsCollection``, ``Statistics``, ``CategoryStatistics``.

DDI-CDI 1.1beta describes the statistics of a variable as one ``StatisticsCollection`` the
``InstanceVariable`` ``isDescribedBy``. Each ``Statistics`` in it is a bundle of ``Statistic``
values of one kind (``typeOfStatistic``); a ``CategoryStatistics`` is the same bundle about
one category of the variable (``for``). Both halves of :mod:`ddicdi.stats` are emitted this
way -- the summary statistics as ``Statistics``, the frequency distributions as
``CategoryStatistics`` with one ``Category`` node per code. A weighted run names the weight
variable on the collection and on every weighted bundle (``hasWeight``).

Everything here is optional; without ``GenerateOptions.include_statistics`` the document
is unchanged, because the two qsv passes cost more than a metadata-only generation does.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any
from ..data import Dataset
from ..models import DatasetMeta, Variable
from .codes import category, category_id, notation, notation_id, part
from ..stats import (
    FREQUENCY_MAX_CARDINALITY,
    KIND_CATEGORICAL,
    QSV_TO_DDI,
    CategoryStats,
    DatasetStats,
    VariableStats,
    category_stats_many,
    summary_stats,
)

Element = dict[str, Any]

# ``Statistic.computationBase``: which cases went into the number.
TOTAL = "Total"
VALID_ONLY = "ValidOnly"
MISSING_ONLY = "MissingOnly"

# Counts of the two, reported next to the statistics qsv itself computes.
VALID_CASES = "validCases"
INVALID_CASES = "invalidCases"
# ``typeOfStatistic`` of a per-category bundle, as in DDI Discovery.
FREQUENCY = "frequency"
PERCENTAGE = "percentage"

# The vocabulary a document can carry, in emission order: the two case counts, the
# summary statistics qsv computes, and the two per-category ones. A request may name a
# subset of it (``GenerateOptions.statistics_include``); ``None`` means all of them.
SUMMARY_NAMES: tuple[str, ...] = tuple(dict.fromkeys(QSV_TO_DDI.values()))
CATEGORY_NAMES: tuple[str, ...] = (FREQUENCY, PERCENTAGE)
STATISTIC_NAMES: tuple[str, ...] = (VALID_CASES, INVALID_CASES, *SUMMARY_NAMES, *CATEGORY_NAMES)


@dataclass
class StatisticsData:
    """What the two qsv passes returned, ready to be serialised."""

    summary: DatasetStats
    categories: list[CategoryStats]
    weighted: bool
    weight: str | None = None  # the weight variable of a weighted run


def wants_categories(include: Collection[str] | None) -> bool:
    """Whether the frequency pass is worth running for this selection."""
    return include is None or any(name in include for name in CATEGORY_NAMES)


def collect(dataset: Dataset, *, weight: str | None = None, with_categories: bool = True) -> StatisticsData:
    """Run ``qsv stats`` over the file and ``qsv frequency`` over its categorical columns.

    ``weight`` is a variable name or ``"auto"``; see :func:`ddicdi.stats.resolve_weight`.
    ``with_categories=False`` skips the frequency pass, for a selection that asked for
    no per-category statistic.
    """
    summary = summary_stats(dataset, weight=weight)
    categories: list[CategoryStats] = []
    if with_categories:
        names = [v.name for v in summary.variables if _has_categories(v)]
        categories = category_stats_many(
            dataset, names, limit=FREQUENCY_MAX_CARDINALITY, weight=summary.weight, sort="code"
        )
    return StatisticsData(summary=summary, categories=categories, weighted=bool(summary.weight), weight=summary.weight)


def _has_categories(v: VariableStats) -> bool:
    """Frequencies for the codelist-like variables only, and only when complete.

    ``VariableStats.has_categories`` is wider than this: it also offers a frequency
    table for any low cardinality column, which is useful in the editor but not worth
    freezing into the document.
    """
    return (
        v.kind == KIND_CATEGORICAL
        and v.has_categories
        and v.cardinality is not None
        and v.cardinality <= FREQUENCY_MAX_CARDINALITY
    )


# -- ids ------------------------------------------------------------------------------


def statistics_collection_id(variable: str) -> str:
    return f"#statisticsCollection-{variable}"


def summary_statistic_id(variable: str, name: str) -> str:
    return f"#statistics-{variable}-{name}"


def category_statistic_id(variable: str, code: str, name: str) -> str:
    return f"#categoryStatistics-{variable}-{part(code)}-{name}"


# -- the pieces -------------------------------------------------------------------------


def _statistic(value: float, *, weighted: bool, base: str) -> Element:
    """A ``Statistic`` value object. ``content`` is xsd:double per the model."""
    return {
        "@type": "Statistic",
        "content": int(value) if float(value).is_integer() else value,
        "isWeighted": weighted,
        "typeOfNumericValue": "double",
        "computationBase": base,
    }


def _bundle(
    el_id: str,
    variable: str,
    name: str,
    statistic: Element,
    category: str | None = None,
    weight: str | None = None,
) -> Element:
    """A ``Statistics`` bundle, or a ``CategoryStatistics`` one when it is about a category."""
    el: Element = {
        "@id": el_id,
        "@type": "CategoryStatistics" if category is not None else "Statistics",
        "typeOfStatistic": {"@type": "ControlledVocabularyEntry", "entryValue": name},
        "statistic": [statistic],
    }
    if category is not None:
        el["for"] = category
    if weight is not None and statistic.get("isWeighted"):
        el["hasWeight"] = f"#instanceVariable-{weight}"
    el["has_StatisticsCollection"] = statistics_collection_id(variable)
    return el


def _summary_base(var: Variable | None, excludes_sentinels: bool) -> str:
    """qsv skips empty cells, so the moments are over the valid cases ...

    ... except where the declared missing codes are in the data (a CSV upload, or an
    SPSS/SAS file read with ``--sentinels-embedded``) and hence counted in.
    """
    if var is not None and var.has_missing and not excludes_sentinels:
        return TOTAL
    return VALID_ONLY


def generate_Statistics(
    meta: DatasetMeta, data: StatisticsData, include: Collection[str] | None = None
) -> list[Element]:
    """One bundle per statistic: the summary ones per variable, then the per-category ones.

    ``include`` names the statistics to keep, out of :data:`STATISTIC_NAMES`; ``None``
    keeps every one of them.
    """
    out: list[Element] = []
    weighted = data.weighted
    weight = data.weight
    by_name = {c.name: c for c in data.categories}
    wanted = None if include is None else set(include)

    def keep(name: str) -> bool:
        return wanted is None or name in wanted

    for v in data.summary.variables:
        if v.is_weight:
            # qsv leaves the weight column out of a weighted run; it has no statistics.
            continue
        base = _summary_base(_var(meta, v.name), data.summary.excludes_sentinels)
        if keep(VALID_CASES):
            out.append(
                _bundle(
                    summary_statistic_id(v.name, VALID_CASES),
                    v.name,
                    VALID_CASES,
                    _statistic(v.valid_n, weighted=False, base=VALID_ONLY),
                    weight=weight,
                )
            )
        if v.missing_n and keep(INVALID_CASES):
            out.append(
                _bundle(
                    summary_statistic_id(v.name, INVALID_CASES),
                    v.name,
                    INVALID_CASES,
                    _statistic(v.missing_n, weighted=False, base=MISSING_ONLY),
                    weight=weight,
                )
            )
        for stat in v.stats:
            if not keep(stat.name):
                continue
            value = _number(stat.value)
            if value is None:
                # A string mode, minimum or maximum of a text column: Statistic.content
                # is xsd:double, so there is nowhere to put it.
                continue
            out.append(
                _bundle(
                    summary_statistic_id(v.name, stat.name),
                    v.name,
                    stat.name,
                    _statistic(value, weighted=weighted, base=base),
                    weight=weight,
                )
            )

        cats = by_name.get(v.name)
        if cats is None:
            continue
        for c in cats.categories:
            ref = category_id(v.name, c.code)
            if keep(FREQUENCY):
                out.append(
                    _bundle(
                        category_statistic_id(v.name, c.code, FREQUENCY),
                        v.name,
                        FREQUENCY,
                        _statistic(c.count, weighted=weighted, base=VALID_ONLY),
                        category=ref,
                        weight=weight,
                    )
                )
            if keep(PERCENTAGE):
                out.append(
                    _bundle(
                        category_statistic_id(v.name, c.code, PERCENTAGE),
                        v.name,
                        PERCENTAGE,
                        _statistic(c.percent, weighted=weighted, base=VALID_ONLY),
                        category=ref,
                        weight=weight,
                    )
                )
    return out


def described_variables(bundles: list[Element]) -> list[str]:
    """The variables the bundles describe, in emission order: each gets one collection."""
    prefix = statistics_collection_id("")
    return list(dict.fromkeys(b["has_StatisticsCollection"].removeprefix(prefix) for b in bundles))


def generate_StatisticsCollection(data: StatisticsData, bundles: list[Element]) -> list[Element]:
    """One ``StatisticsCollection`` per described variable; a weighted run names the weight."""
    out: list[Element] = []
    for name in described_variables(bundles):
        el: Element = {"@id": statistics_collection_id(name), "@type": "StatisticsCollection"}
        if data.weight:
            el["hasWeight"] = f"#instanceVariable-{data.weight}"
        out.append(el)
    return out


def _unlabelled(meta: DatasetMeta, data: StatisticsData) -> list[tuple[str, str, str | None]]:
    """The (variable, code, label) a frequency was computed for but no code list covers.

    A labelled code is already a ``Category`` of the variable's code list and the
    statistic simply points at it; a value that occurs in the data without a label has
    no code list entry, so it needs its own Category and Notation.
    """
    out: list[tuple[str, str, str | None]] = []
    for cats in data.categories:
        var = _var(meta, cats.name)
        for c in cats.categories:
            if var is None or c.code not in var.value_labels:
                out.append((cats.name, c.code, c.label))
    return out


def generate_Category(meta: DatasetMeta, data: StatisticsData) -> list[Element]:
    """The code lists write the very same node for a labelled code."""
    return [category(name, code, label) for name, code, label in _unlabelled(meta, data)]


def generate_Notation(meta: DatasetMeta, data: StatisticsData) -> list[Element]:
    return [notation(name, code) for name, code, _ in _unlabelled(meta, data)]


def _var(meta: DatasetMeta, name: str) -> Variable | None:
    try:
        return meta.var(name)
    except KeyError:
        return None


def _number(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None
