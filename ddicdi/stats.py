"""Per-variable statistics computed by ``qsv stats`` and ``qsv frequency``.

Two things are computed on the cached ``data.csv`` of an upload:

* **summary statistics** for every variable in one ``qsv stats`` pass, and
* **category (frequency) statistics** for the variables that look categorical.

Statistic names are translated into DDI-CDI ``SummaryStatisticType`` terms here,
in :data:`QSV_TO_DDI`, so that emitting them into the JSON-LD is a matter of serialising
what this module already returns; ``cdi/statistics.py`` does that, for the documents
generated with ``include_statistics``. Nothing in this module writes to the DDI-CDI
document.

The summary statistics are over the valid cases: ``qsv stats`` reads
``data.valid.csv``, a copy of ``data.csv`` with the declared missing codes blanked,
so a 99 = Refused is not averaged in. The frequencies read ``data.csv`` itself, so
the missing codes still show up there as sentinel categories.

Caching is qsv's own: ``qsv stats -c 1`` keeps a ``<stem>.stats.csv`` next to the
input and reuses it until the CSV is newer. Every edit that changes data rewrites
``data.csv`` (see ``editing._rewrite``), which makes the valid copy stale; so does a
change to the declared missing values, which the copy records in ``data.valid.key``.
Labels are applied here, per request, and never cached.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import settings
from .data import Dataset
from .models import DatasetMeta, Variable, normalize_number

# qsv's stat names -> DDI-CDI SummaryStatisticType terms. The single place the two
# vocabularies meet. Deliberately unmapped: antimode (emits "*ALL" for unique
# columns), percentiles, geometric_mean, harmonic_mean, sortiness, sparsity,
# max_precision, uniqueness_ratio -- none of them have a DDI-CDI term.
QSV_TO_DDI: dict[str, str] = {
    "min": "minimum",
    "max": "maximum",
    "range": "range",
    "mean": "mean",
    "q2_median": "median",
    "mode": "mode",
    "stddev": "standardDeviation",
    "variance": "variance",
    "sum": "sum",
    "sem": "standardErrorOfMean",
    "cv": "coefficientOfVariation",
    "mad": "medianAbsoluteDeviation",
    "q1": "firstQuartile",
    "q3": "thirdQuartile",
    "iqr": "interquartileRange",
    "skewness": "skewness",
    "cardinality": "cardinality",
    "n_negative": "negativeCount",
    "n_zero": "zeroCount",
    "n_positive": "positiveCount",
    "min_length": "minimumLength",
    "max_length": "maximumLength",
    "avg_length": "averageLength",
}

# Order in which statistics are reported, per kind.
NUMERIC_STATS: tuple[str, ...] = (
    "min", "max", "mean", "q2_median", "mode", "stddev", "variance", "sum", "range",
    "q1", "q3", "iqr", "skewness", "cv", "sem", "mad",
    "n_negative", "n_zero", "n_positive", "cardinality",
)
TEXT_STATS: tuple[str, ...] = (
    "cardinality", "mode", "min_length", "max_length", "avg_length", "min", "max",
)

# A variable with more distinct values than this is not treated as categorical.
# Calibrated on ESS11: ppltrst/hinctnta 11 and dweight 20 are in, stratum 94,
# psu 500 and idno 2420 are out.
CATEGORICAL_MAX_CARDINALITY = 50
# ... but a frequency table is still offered up to here, on request.
FREQUENCY_MAX_CARDINALITY = 200
DEFAULT_CATEGORY_LIMIT = 25

NUMERIC_QSV_TYPES = {"Integer", "Float"}
# qsv's "*HIGH_CARDINALITY" / ">=<n>" sentinels, emitted when --mode-cardinality-cap trips.
HIGH_CARDINALITY = "*HIGH_CARDINALITY"

KIND_NUMERIC = "numeric"
KIND_CATEGORICAL = "categorical"
KIND_TEXT = "text"
KIND_EMPTY = "empty"


@dataclass
class SummaryStat:
    """One statistic, named with its DDI-CDI ``SummaryStatisticType`` term."""

    name: str
    value: str  # qsv's already-rounded string, verbatim


@dataclass
class VariableStats:
    name: str
    kind: str  # numeric | categorical | text | empty
    numeric: bool  # qsv inferred Integer or Float -- orthogonal to ``kind``
    qsv_type: str
    valid_n: int
    missing_n: int
    cardinality: int | None = None
    cardinality_capped: bool = False
    has_categories: bool = False
    is_weight: bool = False
    sentinel_codes: list[str] = field(default_factory=list)
    stats: list[SummaryStat] = field(default_factory=list)


@dataclass
class Category:
    code: str  # normalised, so it matches ``Variable.value_labels``
    label: str | None
    count: float  # float: weighted counts are fractional
    percent: float
    rank: int
    sentinel: bool


@dataclass
class CategoryStats:
    name: str
    label: str | None
    total_rows: int
    valid_n: int
    valid_n_substantive: int  # valid_n minus the sentinel counts
    missing_n: int
    cardinality: int | None
    all_unique: bool
    truncated: bool
    other_count: float
    weight: str | None
    categories: list[Category]


@dataclass
class DatasetStats:
    total_rows: int
    weight: str | None
    weight_candidates: list[str]
    excludes_sentinels: bool
    degraded: bool
    elapsed_ms: int
    variables: list[VariableStats]


# -- weights ------------------------------------------------------------------------


def weight_candidates(meta: DatasetMeta) -> list[str]:
    """Numeric variables carrying the ``Weight`` function, in column order."""
    return [v.name for v in meta.variables if v.numeric and "Weight" in v.functions]


def resolve_weight(meta: DatasetMeta, wanted: str | None) -> str | None:
    """``None`` -> unweighted, ``"auto"`` -> the first candidate, a name -> validated."""
    if not wanted:
        return None
    if wanted == "auto":
        candidates = weight_candidates(meta)
        return candidates[0] if candidates else None
    try:
        var = meta.var(wanted)
    except KeyError:
        raise ValueError(f"Unknown weight variable {wanted!r}")
    if not var.numeric:
        raise ValueError(f"Weight variable {wanted!r} is not numeric")
    return var.name


# -- parsing qsv output -------------------------------------------------------------


def _parse_cardinality(raw: Any) -> tuple[int | None, bool]:
    """qsv emits ``">=100000"`` when --mode-cardinality-cap trips; never assume an int."""
    if raw is None or raw == "":
        return None, False
    if isinstance(raw, str):
        if raw.startswith(">="):
            return None, True
        try:
            return int(float(raw)), False
        except ValueError:
            return None, True
    try:
        return int(raw), False
    except (TypeError, ValueError):
        return None, False


def _stat_value(raw: Any) -> str:
    """qsv values come through verbatim; NaN/inf and ``None`` become an empty string."""
    if raw is None:
        return ""
    if isinstance(raw, float):
        if math.isnan(raw) or math.isinf(raw):
            return ""
        return normalize_number(repr(raw))
    if isinstance(raw, bool):
        return str(raw)
    if isinstance(raw, int):
        return str(raw)
    return normalize_number(str(raw))


def classify(var: Variable | None, qsv_type: str, cardinality: int | None, valid_n: int) -> str:
    if qsv_type == "NULL" or valid_n == 0:
        return KIND_EMPTY
    # A real codelist, not a variable that only labels its missing codes: a
    # calculated age with a single "999 = not available" label is still a scale.
    if var is not None and var.substantive_codes():
        return KIND_CATEGORICAL
    if cardinality is not None and cardinality <= CATEGORICAL_MAX_CARDINALITY:
        if var is not None and var.measure in ("nominal", "ordinal"):
            return KIND_CATEGORICAL
        if qsv_type in ("Integer", "String", "Boolean") and cardinality < valid_n:
            return KIND_CATEGORICAL
    if qsv_type in NUMERIC_QSV_TYPES:
        return KIND_NUMERIC
    return KIND_TEXT


def _variable_stats(
    row: dict, var: Variable | None, total_rows: int, everything: bool
) -> VariableStats:
    qsv_type = str(row.get("type") or "")
    nullcount = int(row.get("nullcount") or 0)
    valid_n = max(total_rows - nullcount, 0)
    cardinality, capped = _parse_cardinality(row.get("cardinality"))
    # ``qsv stats`` counts the empty cells as one distinct value; ``qsv frequency
    # --no-nulls`` does not. Report distinct *values*, so the two agree.
    if cardinality is not None and nullcount > 0:
        cardinality = max(cardinality - 1, 0)

    kind = classify(var, qsv_type, cardinality, valid_n)
    numeric = qsv_type in NUMERIC_QSV_TYPES

    # The stat set follows the storage type, not the kind: a categorical string
    # (cntry) wants length statistics, a categorical number (ppltrst) wants moments.
    if kind == KIND_EMPTY:
        wanted: tuple[str, ...] = ()
    elif numeric:
        wanted = NUMERIC_STATS
    else:
        wanted = TEXT_STATS

    stats: list[SummaryStat] = []
    for key in wanted:
        if key not in row:
            continue
        value = _stat_value(row[key])
        if value == "" or value == HIGH_CARDINALITY:
            continue
        stats.append(SummaryStat(name=QSV_TO_DDI[key], value=value))

    all_unique = cardinality is not None and valid_n > 0 and cardinality >= valid_n
    has_categories = (
        kind == KIND_CATEGORICAL
        or (everything and cardinality is not None and cardinality <= FREQUENCY_MAX_CARDINALITY)
    ) and not all_unique

    return VariableStats(
        name=str(row.get("field") or ""),
        kind=kind,
        numeric=numeric,
        qsv_type=qsv_type,
        valid_n=valid_n,
        missing_n=nullcount,
        cardinality=cardinality,
        cardinality_capped=capped,
        has_categories=has_categories,
        sentinel_codes=var.sentinel_codes() if var else [],
        stats=stats,
    )


# -- valid cases ----------------------------------------------------------------------


def valid_cases_csv(dataset: Dataset) -> tuple[Path, bool]:
    """``data.csv`` with the declared missing codes blanked, and whether it was rewritten.

    Returns ``data.csv`` itself when no declared missing code can be in it.
    """
    meta = dataset.meta
    src = dataset.csv_path
    missing = {v.name: v for v in meta.variables_with_missing}
    if not missing or not meta.sentinels_in_data or not src.exists():
        return src, False

    out = src.with_name(f"{src.stem}.valid.csv")
    key_file = src.with_name(f"{src.stem}.valid.key")
    key = json.dumps({n: [r.to_dict() for r in v.missing_ranges] for n, v in missing.items()}, sort_keys=True)
    if (
        out.exists()
        and key_file.exists()
        and out.stat().st_mtime_ns >= src.stat().st_mtime_ns
        and key_file.read_text(encoding="utf-8") == key
    ):
        return out, False

    tmp = out.with_suffix(".tmp")
    with src.open(newline="", encoding="utf-8") as fin, tmp.open("w", newline="", encoding="utf-8") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        header = next(reader, None)
        if header is None:
            return src, False
        writer.writerow(header)
        cols = [(i, missing[name]) for i, name in enumerate(header) if name in missing]
        for row in reader:
            for i, var in cols:
                if i < len(row) and var.is_missing_code(row[i]):
                    row[i] = ""
            writer.writerow(row)
    tmp.replace(out)
    key_file.write_text(key, encoding="utf-8")
    return out, True


# -- the two entry points -----------------------------------------------------------


def summary_stats(dataset: Dataset, *, weight: str | None = None, force: bool = False) -> DatasetStats:
    """One ``qsv stats`` pass over the whole file."""
    import time

    meta = dataset.meta
    weight = resolve_weight(meta, weight)
    # --everything loads and sorts every numeric column in memory; skip it on big files.
    size = dataset.csv_path.stat().st_size if dataset.csv_path.exists() else 0
    everything = size <= settings.stats_everything_max_bytes

    started = time.perf_counter()
    stats_csv, rewritten = valid_cases_csv(dataset)
    rows = dataset.qsv.stats(
        stats_csv,
        weight=weight,
        everything=everything,
        # a copy rewritten within the same mtime tick could look as old as qsv's cache
        force=force or rewritten,
        timeout=settings.stats_timeout,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    by_name = {str(r.get("field")): r for r in rows}
    variables: list[VariableStats] = []
    for var in meta.variables:
        row = by_name.get(var.name)
        if row is None:
            # qsv excludes the weight column from a weighted run; keep the variable
            # visible so the UI can explain the gap instead of silently dropping it.
            if weight and var.name == weight:
                variables.append(
                    VariableStats(
                        name=var.name,
                        kind=KIND_NUMERIC if var.numeric else KIND_TEXT,
                        numeric=var.numeric,
                        qsv_type="",
                        valid_n=meta.number_rows,
                        missing_n=0,
                        is_weight=True,
                    )
                )
            continue
        variables.append(_variable_stats(row, var, meta.number_rows, everything))

    return DatasetStats(
        total_rows=meta.number_rows,
        weight=weight,
        weight_candidates=weight_candidates(meta),
        # qsv stats reads the valid-cases copy (or cells qsv already wrote empty), so
        # the declared missing codes are never in the moments.
        excludes_sentinels=True,
        degraded=not everything,
        elapsed_ms=elapsed_ms,
        variables=variables,
    )


def category_stats(
    dataset: Dataset,
    name: str,
    *,
    limit: int = DEFAULT_CATEGORY_LIMIT,
    weight: str | None = None,
    sort: str = "count",
) -> CategoryStats:
    """``qsv frequency`` for one variable, with value labels and sentinels applied."""
    return category_stats_many(dataset, [name], limit=limit, weight=weight, sort=sort)[0]


def category_stats_many(
    dataset: Dataset,
    names: list[str],
    *,
    limit: int = DEFAULT_CATEGORY_LIMIT,
    weight: str | None = None,
    sort: str = "count",
) -> list[CategoryStats]:
    """The same for several variables, in one ``qsv frequency`` pass, in the order asked."""
    meta = dataset.meta
    variables = [meta.var(n) for n in names]  # KeyError -> 404 at the route
    weight = resolve_weight(meta, weight)
    if not variables:
        return []
    indexes = [meta.column_names.index(v.name) + 1 for v in variables]

    out = dataset.qsv.frequency(
        dataset.csv_path,
        select=indexes,
        limit=limit,
        weight=weight,
        timeout=settings.stats_timeout,
    )
    total_rows = int(out.get("rowcount") or meta.number_rows)
    by_field = {str(f.get("field")): f for f in out.get("fields") or []}
    return [
        _category_stats(var, by_field.get(var.name) or {}, total_rows, weight, sort) for var in variables
    ]


def _category_stats(
    var: Variable, field_out: dict, total_rows: int, weight: str | None, sort: str
) -> CategoryStats:
    missing_n = int(field_out.get("nullcount") or 0)
    cardinality, _ = _parse_cardinality(field_out.get("cardinality"))

    categories: list[Category] = []
    all_unique = False
    truncated = False
    other_count = 0.0
    for entry in field_out.get("frequencies") or []:
        raw = str(entry.get("value", ""))
        count = float(entry.get("count") or 0)
        rank = int(entry.get("rank") or 0)
        if rank == 0:
            # qsv's roll-up bucket, or its <ALL_UNIQUE> short circuit for ID columns.
            if raw.startswith("<ALL_UNIQUE"):
                all_unique = True
            else:
                truncated = True
                other_count = count
            continue
        code = var.normalize(raw)
        categories.append(
            Category(
                code=code,
                label=var.value_labels.get(code),
                count=count,
                percent=float(entry.get("percentage") or 0.0),
                rank=rank,
                sentinel=var.is_missing_code(code),
            )
        )

    if sort == "code":
        categories.sort(key=_code_sort_key)

    valid_n = max(total_rows - missing_n, 0)
    sentinel_total = sum(c.count for c in categories if c.sentinel)

    return CategoryStats(
        name=var.name,
        label=var.label,
        total_rows=total_rows,
        valid_n=valid_n,
        valid_n_substantive=int(round(valid_n - sentinel_total)),
        missing_n=missing_n,
        cardinality=cardinality,
        all_unique=all_unique,
        truncated=truncated,
        other_count=other_count,
        weight=weight,
        categories=categories,
    )


def _code_sort_key(c: Category) -> tuple[int, float, str]:
    """Numeric codes first and in numeric order; everything else alphabetically."""
    try:
        return (0, float(c.code), "")
    except ValueError:
        return (1, 0.0, c.code)
