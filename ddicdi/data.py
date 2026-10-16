"""Row access on top of the cached CSV produced by the importers."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from .models import DatasetMeta
from .qsv import Qsv


class Dataset:
    """An imported dataset: metadata plus a comma separated CSV with the data.

    Cells are always returned as normalised strings (see ``Variable.normalize``);
    an empty string is a missing value.
    """

    def __init__(self, meta: DatasetMeta, csv_path: Path, qsv: Qsv | None = None) -> None:
        self.meta = meta
        self.csv_path = Path(csv_path)
        self._qsv = qsv

    @property
    def qsv(self) -> Qsv:
        if self._qsv is None:
            self._qsv = Qsv()
        return self._qsv

    def __len__(self) -> int:
        return self.meta.number_rows

    def _normalize_row(self, raw: list[str]) -> list[str]:
        variables = self.meta.variables
        return [variables[i].normalize(cell) if i < len(variables) else cell for i, cell in enumerate(raw)]

    def head(self, n: int) -> list[list[str]]:
        """First ``n`` records, column order as in ``meta.column_names``."""
        if n <= 0:
            return []
        return [self._normalize_row(r) for r in self.qsv.slice(self.csv_path, 0, n)]

    def iter_rows(self, limit: int | None = None) -> Iterator[list[str]]:
        """Stream all records (or the first ``limit``) without loading the file."""
        with self.csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            next(reader, None)  # header
            for i, row in enumerate(reader):
                if limit is not None and i >= limit:
                    break
                yield self._normalize_row(row)

    def iter_chunks(self, chunk_size: int, limit: int | None = None) -> Iterator[tuple[int, list[list[str]]]]:
        """Yield ``(start_index, rows)`` chunks."""
        chunk: list[list[str]] = []
        start = 0
        for i, row in enumerate(self.iter_rows(limit)):
            chunk.append(row)
            if len(chunk) >= chunk_size:
                yield start, chunk
                start = i + 1
                chunk = []
        if chunk:
            yield start, chunk

    def preview(self, n: int) -> list[dict[str, str]]:
        names = self.meta.column_names
        return [dict(zip(names, row)) for row in self.head(n)]
