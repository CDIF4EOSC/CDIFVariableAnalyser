"""Statistics of a document opened from QLever, kept with the metadata-only session.

Such a session has no data, so qsv cannot compute statistics. Instead the ones the saved
CDIF carried (``cdif/reverse.py`` reads them) are stored in the workspace as
``DatasetMeta.saved_statistics`` and stand in for the qsv results, in the output and in
the Statistics tab, for as long as the session has no rows of its own.

They are stored by variable UUID, not name, so a rename in the session keeps them and a
deleted variable drops out. Value labels and missing codes are taken from the current
metadata when they are used. The numbers are what QLever returned: rounded at about the
12th significant digit.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from typing import Any

from .cdi.statistics import StatisticsData
from .models import DatasetMeta
from .stats import Category, CategoryStats, DatasetStats, SummaryStat, VariableStats


def to_dict(data: StatisticsData, meta: DatasetMeta) -> dict[str, Any]:
    """``data`` (variables named) -> the stored form (variables by UUID)."""
    uid = {v.name: v.uid for v in meta.variables}
    out = asdict(data)
    for v in out["summary"]["variables"]:
        v["name"] = uid[v["name"]]
    for c in out["categories"]:
        c["name"] = uid[c["name"]]
    out["summary"]["weight"] = uid.get(out["summary"]["weight"]) if out["summary"]["weight"] else None
    out["weight"] = out["summary"]["weight"]
    return out


def active(meta: DatasetMeta) -> bool:
    return bool(meta.saved_statistics) and meta.number_rows == 0


def load(meta: DatasetMeta) -> StatisticsData | None:
    """The saved statistics, named after the variables as they are now; None when the
    session has data (then qsv computes them) or never had saved ones."""
    if not active(meta):
        return None
    d = meta.saved_statistics
    assert d is not None
    by_uid = {v.uid: v for v in meta.variables}
    weight = by_uid.get(d["summary"]["weight"]) if d["summary"]["weight"] else None
    variables = []
    for raw in d["summary"]["variables"]:
        var = by_uid.get(raw["name"])
        if var is None:
            continue  # deleted in the session
        v = VariableStats(**{**raw, "stats": [SummaryStat(**s) for s in raw["stats"]]})
        v.name = var.name
        v.is_weight = weight is not None and var is weight
        v.sentinel_codes = [c for c in var.value_labels if var.is_missing_code(c)]
        variables.append(v)
    categories = []
    for raw in d["categories"]:
        var = by_uid.get(raw["name"])
        if var is None:
            continue
        cats = [replace(Category(**c), label=var.value_labels.get(c["code"], c["label"]),
                        sentinel=var.is_missing_code(c["code"])) for c in raw["categories"]]
        categories.append(CategoryStats(**{**raw, "name": var.name, "label": var.label, "categories": cats}))
    summary = DatasetStats(**{**d["summary"], "variables": variables, "weight": weight.name if weight else None})
    return StatisticsData(summary=summary, categories=categories, weighted=weight is not None,
                          weight=weight.name if weight else None)


def category(meta: DatasetMeta, name: str, *, limit: int, sort: str) -> CategoryStats | None:
    """One variable's saved frequencies, for the Statistics tab; None when it has none."""
    data = load(meta)
    found = next((c for c in data.categories if c.name == name), None) if data else None
    if found is None:
        return None
    # As qsv frequency does it: the ``limit`` most frequent, then (sort=code) by code.
    by_count = sorted(found.categories, key=lambda c: -c.count)
    kept = by_count[:limit]
    if sort == "code":
        kept.sort(key=_code_order)
    return replace(found, categories=kept, truncated=len(by_count) > limit,
                   other_count=sum(c.count for c in by_count[limit:]))


def _code_order(c: Category):
    try:
        return (0, float(c.code), c.code)
    except ValueError:
        return (1, 0.0, c.code)
