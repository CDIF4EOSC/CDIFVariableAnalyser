"""File import: dispatches on extension and returns a ``Dataset``."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ..data import Dataset
from ..models import DatasetInfo, DatasetMeta
from ..qsv import Qsv
from .csv_reader import import_csv
from .parquet import import_parquet
from .readstat import FILE_FORMAT_BY_EXT, import_readstat

CSV_EXTENSIONS = {".csv", ".tsv", ".txt"}
PARQUET_EXTENSIONS = {".parquet"}
SUPPORTED_EXTENSIONS = set(FILE_FORMAT_BY_EXT) | CSV_EXTENSIONS | PARQUET_EXTENSIONS


def import_file(path: Path, work_dir: Path, qsv: Qsv | None = None, datafile: str | None = None) -> Dataset:
    """Import ``path`` and cache its data as ``work_dir/data.csv``."""
    qsv = qsv or Qsv()
    path = Path(path)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    out_csv = work_dir / "data.csv"

    ext = path.suffix.lower()
    if ext in FILE_FORMAT_BY_EXT:
        meta = import_readstat(path, out_csv, qsv, datafile)
    elif ext in CSV_EXTENSIONS:
        meta = import_csv(path, out_csv, qsv, datafile)
    elif ext in PARQUET_EXTENSIONS:
        meta = import_parquet(path, out_csv, qsv, datafile)
    else:
        raise ValueError(f"Unsupported file type {ext!r}. Supported: {sorted(SUPPORTED_EXTENSIONS)}")
    meta.info = suggested_info(meta)
    return Dataset(meta, out_csv, qsv)


def suggested_info(meta: DatasetMeta) -> DatasetInfo:
    """The dataset description an upload starts with, for the user to correct.

    The title is the file label (SPSS, Stata) or else the file name; both dates are the
    upload day.
    """
    stem = Path(meta.datafile).stem
    today = date.today().isoformat()
    return DatasetInfo(
        title=(meta.file_label or "").strip() or stem,
        record_id=f"urn:ddi-cdi:{stem}",
        version="1.0",
        language="en",
        date_published=today,
        date_modified=today,
    )
