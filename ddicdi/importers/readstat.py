"""Import SPSS / Stata / SAS files through ``qsv readstat``.

Two qsv calls per file: ``--metadata json`` for the variable dictionary and a
streaming conversion of the data to ``data.csv``. For SPSS and SAS files the
conversion keeps user-missing codes in the cells (``--sentinels-as value
--sentinels-embedded``), so they reach the SentinelValueDomain. Stata files, .por
and .xpt, and qsv builds without the option, still get empty cells there.
"""

from __future__ import annotations

import csv
import math
import re
from pathlib import Path

from ..models import DatasetMeta, MissingRange, Variable
from ..qsv import SENTINEL_EXTENSIONS, Qsv

# readstat / SPSS format type codes -> format name
SPSS_FORMAT_NAMES = {
    1: "A", 2: "AHEX", 3: "COMMA", 4: "DOLLAR", 5: "F", 6: "IB", 7: "PIBHEX", 8: "P",
    9: "PIB", 10: "PK", 11: "RB", 12: "RBHEX", 15: "Z", 16: "N", 17: "E",
    20: "DATE", 21: "TIME", 22: "DATETIME", 23: "ADATE", 24: "JDATE", 25: "DTIME",
    26: "WKDAY", 27: "MONTH", 28: "MOYR", 29: "QYR", 30: "WKYR", 31: "PCT", 32: "DOT",
    33: "CCA", 34: "CCB", 35: "CCC", 36: "CCD", 37: "CCE", 38: "EDATE", 39: "SDATE",
    40: "MTIME", 41: "YMDHMS",
}
_SPSS_DATE_TYPES = {20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 38, 39, 40, 41}
_SPSS_STRING_TYPES = {1, 2}

_STATA_TYPE_MAP = {
    "byte": "int8",
    "int": "int16",
    "long": "int32",
    "float": "float",
    "double": "double",
}

FILE_FORMAT_BY_EXT = {
    ".sav": "spss", ".zsav": "spss", ".por": "spss",
    ".dta": "stata",
    ".sas7bdat": "sas", ".xpt": "sas", ".xpt5": "sas", ".xpt8": "sas",
}


def spss_format_string(format_type: int, width: int, decimals: int) -> str:
    name = SPSS_FORMAT_NAMES.get(format_type, f"UNKNOWN{format_type}")
    if format_type in _SPSS_STRING_TYPES:
        return f"{name}{width}"
    if format_type in _SPSS_DATE_TYPES:
        return f"{name}{width}.{decimals}" if decimals else f"{name}{width}"
    return f"{name}{width}.{decimals}"


def _measure(value: str | None) -> str:
    m = (value or "unknown").lower()
    return m if m in ("nominal", "ordinal", "scale") else "unknown"


def _spss_missing_ranges(v: dict) -> list[MissingRange]:
    ranges: list[MissingRange] = []
    doubles = list(v.get("missing_doubles") or [])
    if v.get("missing_range") and len(doubles) >= 2:
        lo, hi = doubles[0], doubles[1]
        if hi >= 1.7e308:
            hi = math.inf
        if lo <= -1.7e308:
            lo = -math.inf
        ranges.append(MissingRange(float(lo), float(hi)))
        doubles = doubles[2:]
    ranges.extend(MissingRange(float(d), float(d)) for d in doubles)
    ranges.extend(MissingRange(s, s) for s in (v.get("missing_strings") or []))
    return ranges


def _spss_variable(v: dict) -> Variable:
    is_string = v.get("type") == "Str"
    return Variable(
        name=v["name"],
        label=v.get("label"),
        format=spss_format_string(v.get("format_type", 5), v.get("format_width", 8), v.get("format_decimals", 0)),
        storage_type="string" if is_string else "double",
        measure=_measure(v.get("measure")),
        numeric=not is_string,
        value_labels={str(k): str(lbl) for k, lbl in (v.get("value_labels") or {}).items()},
        missing_ranges=_spss_missing_ranges(v),
    )


def _stata_variable(v: dict) -> Variable:
    type_str = str(v.get("type", ""))
    m = re.match(r"Numeric\((\w+)\)", type_str)
    if m:
        storage = _STATA_TYPE_MAP.get(m.group(1).lower(), "double")
        numeric = True
    else:
        storage, numeric = "string", False
    return Variable(
        name=v["name"],
        label=v.get("label"),
        format=v.get("format") or "",
        storage_type=storage,
        measure="unknown",
        numeric=numeric,
        value_labels={str(k): str(lbl) for k, lbl in (v.get("value_labels") or {}).items()},
        missing_ranges=[],  # Stata extended missing values are not exposed by qsv metadata
    )


def _sas_variable(v: dict) -> Variable:
    type_str = str(v.get("type", "")).lower()
    numeric = "num" in type_str or "double" in type_str or "float" in type_str
    return Variable(
        name=v["name"],
        label=v.get("label"),
        format=str(v.get("format") or ""),
        storage_type="double" if numeric else "string",
        measure="unknown",
        numeric=numeric,
        value_labels={},
        missing_ranges=[],
    )


def metadata_from_readstat(meta_json: dict, datafile: str, file_format: str) -> DatasetMeta:
    if file_format == "spss":
        variables = [_spss_variable(v) for v in meta_json.get("variables", [])]
    elif file_format == "stata":
        variables = [_stata_variable(v) for v in meta_json.get("variables", [])]
    else:
        variables = [_sas_variable(v) for v in meta_json.get("columns", meta_json.get("variables", []))]

    return DatasetMeta(
        variables=variables,
        number_rows=int(meta_json.get("row_count") or 0),
        datafile=datafile,
        file_format=file_format,
        delimiter=None,
        encoding=meta_json.get("encoding"),
        file_label=meta_json.get("file_label") or meta_json.get("data_label"),
    )


_INTEGER_RE = re.compile(r"-?\d+")


def _match_sentinel_form(meta: DatasetMeta, csv_path: Path) -> None:
    """Write kept missing codes the way qsv writes the column's other numbers.

    qsv renders a numeric value as ``6.0`` but an embedded sentinel as ``6``, so
    ``qsv frequency`` and ``qsv stats`` would see two spellings of one value.
    """
    numeric = {v.name: v for v in meta.variables if v.numeric and v.missing_ranges}
    if not numeric:
        return
    tmp = csv_path.with_suffix(".tmp")
    with csv_path.open(newline="", encoding="utf-8") as fin, tmp.open("w", newline="", encoding="utf-8") as fout:
        reader = csv.reader(fin)
        writer = csv.writer(fout)
        header = next(reader, None)
        if header is None:
            return
        writer.writerow(header)
        cols = [(i, numeric[name]) for i, name in enumerate(header) if name in numeric]
        for row in reader:
            for i, var in cols:
                if i < len(row) and _INTEGER_RE.fullmatch(row[i]) and var.is_missing_code(row[i]):
                    row[i] += ".0"
            writer.writerow(row)
    tmp.replace(csv_path)


def import_readstat(path: Path, out_csv: Path, qsv: Qsv, datafile: str | None = None) -> DatasetMeta:
    """Read metadata with qsv and stream the data to ``out_csv``."""
    ext = path.suffix.lower()
    file_format = FILE_FORMAT_BY_EXT.get(ext)
    if file_format is None:
        raise ValueError(f"Unsupported statistical file extension: {ext}")

    meta = metadata_from_readstat(qsv.readstat_metadata(path), datafile or path.name, file_format)
    keep = ext in SENTINEL_EXTENSIONS and qsv.supports_sentinels
    qsv.readstat_to_csv(path, out_csv, keep_sentinels=keep)
    meta.sentinels_in_data = keep
    if keep:
        _match_sentinel_form(meta, out_csv)
    if not meta.number_rows:
        meta.number_rows = qsv.count(out_csv)
    return meta
