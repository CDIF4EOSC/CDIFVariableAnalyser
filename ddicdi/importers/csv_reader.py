"""Import delimited text files with ``qsv sniff`` + ``qsv input``.

``qsv sniff`` guesses delimiter, header row and column types from a sample. That
guess is verified against a parsed sample of the file before it is trusted: free
text columns (a user agent string such as ``Windows NT 10.0; Win64; x64``) can make
the sniffer pick the wrong delimiter and then report "no header row" for a file that
has one. When the sniff is not trustworthy, names come from ``qsv headers`` and
types from ``qsv stats`` on the normalised copy. The same stats pass yields each
column's width and decimals, which are written as an SPSS style print format
(``F5.2``, ``A14``, ``SDATE10``) so the editor can show and change them.
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..models import DatasetMeta, Variable
from ..qsv import Qsv

# qsv sniff / stats type names -> (storage_type, measure, numeric)
_SNIFF_TYPES = {
    "unsigned": ("numeric", "scale", True),
    "signed": ("numeric", "scale", True),
    "integer": ("numeric", "scale", True),
    "float": ("numeric", "scale", True),
    "date": ("datetime", "nominal", False),
    "datetime": ("datetime", "nominal", False),
    "boolean": ("boolean", "nominal", False),
    "text": ("string", "nominal", False),
    "string": ("string", "nominal", False),
    "null": ("string", "nominal", False),
}

_EXTENSION_DELIMITERS = {".tsv": "\t", ".tab": "\t", ".ssv": ";", ".psv": "|"}
_CANDIDATE_DELIMITERS = (",", ";", "\t", "|")
_SAMPLE_ROWS = 200


def _sample_rows(path: Path, delimiter: str, quote_char: str = '"') -> list[list[str]]:
    """The first ``_SAMPLE_ROWS`` records of ``path`` parsed with ``delimiter``."""
    rows: list[list[str]] = []
    try:
        with path.open(newline="", encoding="utf-8", errors="replace") as fh:
            for row in csv.reader(fh, delimiter=delimiter, quotechar=quote_char or '"'):
                if row:
                    rows.append(row)
                if len(rows) >= _SAMPLE_ROWS:
                    break
    except csv.Error:
        return []
    return rows


def _is_consistent(rows: list[list[str]]) -> bool:
    """Every sampled record has the same field count, and more than one field."""
    return bool(rows) and len(rows[0]) > 1 and len({len(r) for r in rows}) == 1


def _choose_delimiter(path: Path, sniffed: str, quote_char: str) -> tuple[str, list[list[str]]]:
    """Return the first delimiter that splits the sample into a rectangular table.

    Preference order: what qsv sniffed, the file extension's conventional delimiter,
    then the remaining common delimiters. Falls back to the sniffed delimiter when
    nothing is consistent (e.g. a genuine one-column file).
    """
    candidates: list[str] = []
    for d in (sniffed, _EXTENSION_DELIMITERS.get(path.suffix.lower(), ","), *_CANDIDATE_DELIMITERS):
        if d and d not in candidates:
            candidates.append(d)
    for d in candidates:
        rows = _sample_rows(path, d, quote_char)
        if _is_consistent(rows):
            return d, rows
    return sniffed, _sample_rows(path, sniffed, quote_char)


def _is_number(value: str) -> bool:
    try:
        float(value.replace(",", ".", 1))
    except ValueError:
        return False
    return True


def _looks_like_header(rows: list[list[str]]) -> bool:
    """First row is a plausible header: unique, non-empty, non-numeric names."""
    if not rows:
        return False
    first = [c.strip() for c in rows[0]]
    if any(c == "" for c in first) or len(set(first)) != len(first):
        return False
    if any(_is_number(c) for c in first):
        return False
    return len(rows) == 1 or rows[1] != rows[0]


def _int_digits(value: object) -> int:
    """Characters before the decimal point of a number rendered by qsv (sign included)."""
    text = str(value)
    return len(text.split(".", 1)[0]) if text else 0


def csv_format(storage: str, profile: dict | None) -> str:
    """SPSS style print format for a sniffed CSV column, from ``Qsv.column_profiles``."""
    profile = profile or {}
    if storage == "numeric":
        decimals = int(profile.get("max_precision") or 0)
        digits = max(_int_digits(profile.get("min", "")), _int_digits(profile.get("max", "")), 1)
        width = digits + (decimals + 1 if decimals else 0)
        return f"F{width}.{decimals}" if profile else "F8.2"
    if storage == "datetime":
        width = max(len(str(profile.get("min", ""))), len(str(profile.get("max", ""))))
        if not width:
            return "DATETIME20"
        return f"SDATE{width}" if profile.get("type") == "Date" else f"DATETIME{width}"
    width = int(profile.get("max_length") or 0)
    return f"A{max(width, 1)}" if profile else "A8"


def variables_from_profiles(fields: list[str], types: list[str], profiles: list[dict]) -> list[Variable]:
    """One ``Variable`` per column, typed from qsv sniff/stats type names."""
    if len(profiles) != len(fields):
        profiles = [{} for _ in fields]
    variables = []
    for name, t, profile in zip(fields, types, profiles):
        storage, measure, numeric = _SNIFF_TYPES.get(str(t).lower(), ("string", "nominal", False))
        variables.append(
            Variable(
                name=name, label=name, format=csv_format(storage, profile),
                storage_type=storage, measure=measure, numeric=numeric,
            )
        )
    return variables


def import_csv(path: Path, out_csv: Path, qsv: Qsv, datafile: str | None = None) -> DatasetMeta:
    info = qsv.sniff(path)
    sniffed_delimiter = info.get("delimiter_char") or ","
    quote_char = info.get("quote_char") or '"'

    delimiter, sample = _choose_delimiter(path, sniffed_delimiter, quote_char)
    sniff_trusted = (
        delimiter == sniffed_delimiter
        and not info.get("flexible", False)
        and bool(info.get("header_row", False))
        and bool(sample)
        and len(info.get("fields") or []) == len(sample[0])
    )

    if not (sniff_trusted or _looks_like_header(sample)):
        raise ValueError("CSV files without a header row are not supported")

    # Cache a normalised, comma separated copy so slice/count/stream never need the delimiter.
    qsv.normalize_csv(path, out_csv, delimiter)

    profiles = qsv.column_profiles(out_csv)
    if sniff_trusted:
        fields = info["fields"]
        types = info.get("types") or ["Text"] * len(fields)
    else:
        fields = qsv.headers(out_csv)
        types = [p["type"] for p in profiles]
        if len(types) != len(fields):
            types = ["Text"] * len(fields)
    variables = variables_from_profiles(fields, types, profiles)

    number_rows = info.get("num_records") if sniff_trusted else None
    if number_rows is None or info.get("estimated"):
        number_rows = qsv.count(out_csv)

    return DatasetMeta(
        variables=variables,
        number_rows=int(number_rows),
        datafile=datafile or path.name,
        file_format="csv",
        delimiter=delimiter,
        encoding="utf-8" if info.get("is_utf8", True) else None,
        sentinels_in_data=True,
    )
