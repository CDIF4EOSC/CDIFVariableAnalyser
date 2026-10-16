"""Import Parquet files through ``qsv sqlp``.

The file is converted to ``data.csv`` once. After that it goes through the same
engine as a CSV upload: column types, widths and decimals come from ``qsv stats`` on
the converted copy. Parquet has no variable labels, value labels or declared missing
values, so those start empty and are added in the editor. Nested columns (lists,
structs) have no CSV form and are refused.
"""

from __future__ import annotations

from pathlib import Path

from ..models import DatasetMeta
from ..qsv import Qsv, QsvError
from .csv_reader import variables_from_profiles


def import_parquet(path: Path, out_csv: Path, qsv: Qsv, datafile: str | None = None) -> DatasetMeta:
    try:
        qsv.parquet_to_csv(path, out_csv)
    except QsvError as exc:
        if "nested data" in str(exc):
            raise ValueError("Parquet files with nested columns (lists, structs) are not supported") from exc
        raise

    fields = qsv.headers(out_csv)
    profiles = qsv.column_profiles(out_csv)
    types = [p["type"] for p in profiles] if len(profiles) == len(fields) else ["Text"] * len(fields)

    return DatasetMeta(
        variables=variables_from_profiles(fields, types, profiles),
        number_rows=qsv.count(out_csv),
        datafile=datafile or path.name,
        file_format="parquet",
        # Every value is in data.csv as stored; missing codes declared later are there too.
        sentinels_in_data=True,
    )
