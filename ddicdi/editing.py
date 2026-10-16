"""In-place edits of an imported dataset: metadata, cells, columns and rows.

The editor UI works on the cached ``data.csv`` + ``meta.json`` of an upload.
Column and cell edits rewrite the CSV in a streaming pass (the files are
small compared to the original statistical file and the pass is O(rows)),
so no engine call is needed after the initial import.
"""

from __future__ import annotations

import csv
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .data import Dataset
from .models import Concept, DatasetMeta, MissingRange, Variable, normalize_number
from .functions import parse_functions
from .roles import ROLE_NAMES, parse_roles

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.@#$]*$")
_NUMERIC_TYPES = {"double", "float", "int8", "int16", "int32", "int64", "numeric", "integer"}


class EditError(ValueError):
    """A rejected edit (unknown variable, bad name, bad value ...)."""


# -- metadata ---------------------------------------------------------------------


@dataclass
class VariablePatch:
    """Fields of a variable that the editor may change. ``None`` = untouched."""

    label: str | None = None
    format: str | None = None
    storage_type: str | None = None
    measure: str | None = None
    value_labels: dict[str, str] | None = None
    missing: list[dict[str, Any]] | None = None
    role: str | None = None
    unit_of_measure: str | None = None  # "" clears
    concepts: list[dict[str, Any]] | None = None  # [{"uri": ..., "pref_label": ...}]
    functions: list[str] | None = None  # ["Weight", ...]; [] clears


def _parse_unit(text: str) -> str | None:
    text = text.strip()
    if not text:
        return None
    if not text.startswith(("http://", "https://")):
        raise EditError(f"Unit of measure must be a URI, got {text!r}")
    return text


def _parse_functions(items: Iterable[str]) -> list[str]:
    try:
        return parse_functions(items)
    except ValueError as exc:
        raise EditError(str(exc))


def _parse_concepts(items: Iterable[dict[str, Any]]) -> list[Concept]:
    out: list[Concept] = []
    seen: set[str] = set()
    for c in items:
        uri = str(c.get("uri", "") or "").strip()
        if not uri or uri in seen:
            continue
        if not uri.startswith(("http://", "https://")):
            raise EditError(f"Concept URI must start with http(s)://, got {uri!r}")
        seen.add(uri)
        out.append(Concept(uri=uri, pref_label=str(c.get("pref_label", "") or "").strip()))
    return out


def _parse_missing(var_numeric: bool, ranges: Iterable[dict[str, Any]]) -> list[MissingRange]:
    out: list[MissingRange] = []
    for r in ranges:
        lo, hi = r.get("lo"), r.get("hi", r.get("lo"))
        if lo is None:
            raise EditError("Missing range needs at least 'lo'")
        if var_numeric:
            try:
                flo = math.inf if lo in ("inf", "+inf") else (-math.inf if lo == "-inf" else float(lo))
                fhi = math.inf if hi in ("inf", "+inf") else (-math.inf if hi == "-inf" else float(hi))
            except (TypeError, ValueError):
                raise EditError(f"Missing range {lo!r}-{hi!r} is not numeric")
            if fhi < flo:
                flo, fhi = fhi, flo
            out.append(MissingRange(flo, fhi))
        else:
            out.append(MissingRange(str(lo), str(hi)))
    return out


def _set_role(meta: DatasetMeta, name: str, role: str) -> None:
    for r in ROLE_NAMES:
        lst = getattr(meta.roles, r)
        if name in lst:
            lst.remove(name)
    parts = [p.strip().lower() for p in role.split(",") if p.strip()] or ["measure"]
    for p in parts:
        if p not in ROLE_NAMES:
            raise EditError(f"Unknown role {p!r}; valid: {ROLE_NAMES}")
        getattr(meta.roles, p).append(name)


def ensure_roles(meta: DatasetMeta) -> None:
    """Make sure every variable has a role (default ``measure``)."""
    assigned = set(meta.roles.measure) | set(meta.roles.identifier) | set(meta.roles.attribute)
    for name in meta.column_names:
        if name not in assigned:
            meta.roles.measure.append(name)
    # drop roles of variables that no longer exist
    names = set(meta.column_names)
    for r in ROLE_NAMES:
        setattr(meta.roles, r, [n for n in getattr(meta.roles, r) if n in names])


def set_roles(meta: DatasetMeta, assignments: dict[str, str]) -> None:
    """Replace all roles from ``{"idno": "identifier", ...}`` (unlisted -> measure)."""
    try:
        meta.roles = parse_roles(meta, assignments)
    except ValueError as exc:
        raise EditError(str(exc))


_FORMAT_RE = re.compile(r"^%?([A-Za-z]*)(\d+)(?:\.(\d+))?[A-Za-z]*$")


def check_format(fmt: str) -> str:
    """Reject print formats SPSS would refuse: zero width, or decimals not smaller than the width."""
    fmt = fmt.strip()
    m = _FORMAT_RE.match(fmt)
    if not m:
        return fmt  # SAS "BEST12." and other shapes are passed through untouched
    width, decimals = int(m.group(2)), int(m.group(3) or 0)
    if width < 1:
        raise EditError(f"Format {fmt!r}: the field width must be at least 1")
    if decimals >= width:
        raise EditError(f"Format {fmt!r}: the number of decimal places is too large for the field width")
    return fmt


def update_variable(meta: DatasetMeta, name: str, patch: VariablePatch) -> Variable:
    try:
        var = meta.var(name)
    except KeyError:
        raise EditError(f"Unknown variable {name!r}")
    if patch.label is not None:
        var.label = patch.label or None
    if patch.format is not None:
        var.format = check_format(patch.format)
    if patch.storage_type is not None:
        var.storage_type = patch.storage_type.strip().lower()
        var.numeric = var.storage_type in _NUMERIC_TYPES
    if patch.measure is not None:
        m = patch.measure.strip().lower()
        if m not in ("nominal", "ordinal", "scale", "unknown"):
            raise EditError(f"Unknown measure {m!r}")
        var.measure = m
    if patch.value_labels is not None:
        cleaned = {}
        for code, label in patch.value_labels.items():
            code = str(code).strip()
            if code == "":
                continue
            cleaned[normalize_number(code) if var.numeric else code] = str(label)
        var.value_labels = cleaned
    if patch.missing is not None:
        var.missing_ranges = _parse_missing(var.numeric, patch.missing)
    if patch.role is not None:
        _set_role(meta, name, patch.role)
    if patch.unit_of_measure is not None:
        var.unit_of_measure = _parse_unit(patch.unit_of_measure)
    if patch.concepts is not None:
        var.concepts = _parse_concepts(patch.concepts)
    if patch.functions is not None:
        var.functions = _parse_functions(patch.functions)
    return var


# -- CSV rewriting -------------------------------------------------------------------


def _rewrite(dataset: Dataset, transform: Callable[[list[str], int], list[str] | None], header: list[str]) -> int:
    """Stream ``data.csv`` through ``transform(row, index)``; returns the row count.

    ``transform`` returns the new row or ``None`` to drop it.
    """
    src = dataset.csv_path
    tmp = src.with_suffix(".csv.tmp")
    count = 0
    with src.open(newline="", encoding="utf-8") as fin, tmp.open("w", newline="", encoding="utf-8") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout, lineterminator="\n")
        next(reader, None)
        writer.writerow(header)
        for i, row in enumerate(reader):
            new = transform(row, i)
            if new is not None:
                writer.writerow(new)
                count += 1
    os.replace(tmp, src)
    return count


@dataclass
class NewVariable:
    name: str
    label: str | None = None
    format: str = "A8"
    storage_type: str = "string"
    measure: str = "nominal"
    value_labels: dict[str, str] = field(default_factory=dict)
    missing: list[dict[str, Any]] = field(default_factory=list)
    role: str = "measure"
    fill: str = "empty"  # empty | constant | copy
    fill_value: str = ""  # constant value or the name of the column to copy
    position: int | None = None  # insert index; None = append
    unit_of_measure: str | None = None
    concepts: list[dict[str, Any]] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)


def add_variable(dataset: Dataset, spec: NewVariable) -> Variable:
    meta = dataset.meta
    name = spec.name.strip()
    if not _NAME_RE.match(name):
        raise EditError(f"Invalid variable name {name!r}")
    if name in meta.column_names:
        raise EditError(f"Variable {name!r} already exists")
    numeric = spec.storage_type.strip().lower() in _NUMERIC_TYPES
    var = Variable(
        name=name,
        label=spec.label or None,
        format=check_format(spec.format) or ("F8.2" if numeric else "A8"),
        storage_type=spec.storage_type.strip().lower(),
        measure=spec.measure if spec.measure in ("nominal", "ordinal", "scale", "unknown") else "unknown",
        numeric=numeric,
        value_labels={str(k): str(v) for k, v in spec.value_labels.items() if str(k).strip()},
        missing_ranges=_parse_missing(numeric, spec.missing),
        unit_of_measure=_parse_unit(spec.unit_of_measure or ""),
        concepts=_parse_concepts(spec.concepts),
        functions=_parse_functions(spec.functions),
    )

    if spec.fill == "constant":
        cell_for: Callable[[list[str]], str] = lambda row: spec.fill_value
    elif spec.fill == "copy":
        if spec.fill_value not in meta.column_names:
            raise EditError(f"Cannot copy unknown column {spec.fill_value!r}")
        src_idx = meta.column_names.index(spec.fill_value)
        cell_for = lambda row: row[src_idx] if src_idx < len(row) else ""
    else:
        cell_for = lambda row: ""

    pos = len(meta.variables) if spec.position is None else max(0, min(spec.position, len(meta.variables)))
    header = meta.column_names
    header.insert(pos, name)

    def transform(row: list[str], _i: int) -> list[str]:
        row = list(row) + [""] * (len(meta.variables) - len(row))
        row.insert(pos, cell_for(row))
        return row

    meta.number_rows = _rewrite(dataset, transform, header)
    meta.variables.insert(pos, var)
    _set_role(meta, name, spec.role)
    return var


def delete_variable(dataset: Dataset, name: str) -> None:
    meta = dataset.meta
    if name not in meta.column_names:
        raise EditError(f"Unknown variable {name!r}")
    if len(meta.variables) == 1:
        raise EditError("Cannot delete the last variable")
    idx = meta.column_names.index(name)
    header = [n for n in meta.column_names if n != name]

    def transform(row: list[str], _i: int) -> list[str]:
        return [c for i, c in enumerate(row) if i != idx]

    meta.number_rows = _rewrite(dataset, transform, header)
    del meta.variables[idx]
    ensure_roles(meta)


def rename_variable(dataset: Dataset, name: str, new_name: str) -> Variable:
    meta = dataset.meta
    new_name = new_name.strip()
    if name not in meta.column_names:
        raise EditError(f"Unknown variable {name!r}")
    if not _NAME_RE.match(new_name):
        raise EditError(f"Invalid variable name {new_name!r}")
    if new_name != name and new_name in meta.column_names:
        raise EditError(f"Variable {new_name!r} already exists")
    header = [new_name if n == name else n for n in meta.column_names]
    _rewrite(dataset, lambda row, _i: row, header)
    var = meta.var(name)
    var.name = new_name
    for r in ROLE_NAMES:
        lst = getattr(meta.roles, r)
        setattr(meta.roles, r, [new_name if n == name else n for n in lst])
    return var


def update_cells(dataset: Dataset, row_index: int, values: dict[str, str]) -> list[str]:
    """Set ``values`` (variable -> new cell text) on row ``row_index``; returns the row."""
    meta = dataset.meta
    if row_index < 0 or row_index >= meta.number_rows:
        raise EditError(f"Row {row_index} out of range (0..{meta.number_rows - 1})")
    unknown = set(values) - set(meta.column_names)
    if unknown:
        raise EditError(f"Unknown variables: {sorted(unknown)}")
    idx = {n: i for i, n in enumerate(meta.column_names)}
    result: list[str] = []

    def transform(row: list[str], i: int) -> list[str]:
        if i != row_index:
            return row
        row = list(row) + [""] * (len(meta.variables) - len(row))
        for name, value in values.items():
            row[idx[name]] = "" if value is None else str(value)
        result.extend(row)
        return row

    _rewrite(dataset, transform, meta.column_names)
    return result


def append_row(dataset: Dataset, values: dict[str, str] | None = None) -> int:
    """Append one record; returns its index."""
    meta = dataset.meta
    values = values or {}
    unknown = set(values) - set(meta.column_names)
    if unknown:
        raise EditError(f"Unknown variables: {sorted(unknown)}")
    row = ["" if values.get(n) is None else str(values.get(n, "")) for n in meta.column_names]
    with dataset.csv_path.open("a", newline="", encoding="utf-8") as fh:
        csv.writer(fh, lineterminator="\n").writerow(row)
    meta.number_rows += 1
    return meta.number_rows - 1


def delete_row(dataset: Dataset, row_index: int) -> None:
    meta = dataset.meta
    if row_index < 0 or row_index >= meta.number_rows:
        raise EditError(f"Row {row_index} out of range (0..{meta.number_rows - 1})")
    meta.number_rows = _rewrite(dataset, lambda row, i: None if i == row_index else row, meta.column_names)


def touch(path: Path) -> None:
    """Refresh the upload directory's mtime so TTL cleanup treats it as active."""
    os.utime(path, None)
