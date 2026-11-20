"""Bounds on what a variable may carry (GitLab #8, #12).

The generator writes per-variable and per-code elements whose size grows with names,
labels and codes, and the build budget charges a fixed amount per variable and per code.
These checks keep that charge honest: every path that creates or changes a variable
(import, the edit API, Open from QLever) refuses a variable over the limits in
``settings`` instead of storing it.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from .config import settings
from .models import DatasetMeta, Variable


class LimitError(ValueError):
    """A variable, or a set of variables, over one of the configured limits."""


def check_count(n_vars: int) -> None:
    limit = settings.max_variables
    if limit > 0 and n_vars > limit:
        raise LimitError(f"the file has {n_vars} variables; the limit is {limit}")


def check_name(name: str) -> None:
    if len(name) > settings.max_name_chars:
        raise LimitError(
            f"variable name {name[:40]!r}... is {len(name)} characters long; the limit is {settings.max_name_chars}"
        )


def check_label(label: str | None, what: str = "label") -> None:
    if label is not None and len(label) > settings.max_label_chars:
        raise LimitError(f"a {what} is {len(label)} characters long; the limit is {settings.max_label_chars}")


def check_value_labels(name: str, labels: Mapping[str, str]) -> None:
    if len(labels) > settings.max_value_labels:
        raise LimitError(
            f"variable {name!r} has {len(labels)} value labels; the limit is {settings.max_value_labels}"
        )
    for code, label in labels.items():
        if len(str(code)) > settings.max_code_chars:
            raise LimitError(
                f"variable {name!r} has a value-label code of {len(str(code))} characters; "
                f"the limit is {settings.max_code_chars}"
            )
        check_label(None if label is None else str(label), "value label")


def check_missing(name: str, ranges: Iterable) -> None:
    n = sum(1 for _ in ranges)
    if n > settings.max_missing_ranges:
        raise LimitError(f"variable {name!r} has {n} missing values or ranges; the limit is {settings.max_missing_ranges}")


def check_format(name: str, value: str | None, what: str = "format") -> None:
    if value is not None and len(value) > settings.max_format_chars:
        raise LimitError(
            f"variable {name!r} has a {what} of {len(value)} characters; the limit is {settings.max_format_chars}"
        )


def check_variable(var: Variable) -> None:
    check_name(var.name)
    check_format(var.name, var.format)
    check_format(var.name, var.storage_type, "storage type")
    check_label(var.label, "variable label")
    check_value_labels(var.name, var.value_labels)
    check_missing(var.name, var.missing_ranges)


def check_meta(meta: DatasetMeta) -> None:
    """Every limit, for a whole dataset (after an import, or a document read back)."""
    check_count(len(meta.variables))
    for var in meta.variables:
        check_variable(var)


def code_count(meta: DatasetMeta) -> int:
    """Labelled codes of the dataset: each becomes a Code, CodePosition, Category and Notation."""
    return sum(len(v.value_labels) for v in meta.variables)
