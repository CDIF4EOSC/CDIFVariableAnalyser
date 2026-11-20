"""Row access on top of the cached CSV produced by the importers."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from .config import settings
from .models import DatasetMeta
from .qsv import Qsv


class DataTooLarge(ValueError):
    """The rows a document build asked for hold more bytes than it was admitted for."""


def row_bytes(row: list[str]) -> int:
    """The size of a record as counted against a build's byte limit (characters plus
    one separator per cell; close to its CSV bytes for ASCII text)."""
    return sum(len(c) for c in row) + len(row)


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

    def head(self, n: int, max_bytes: int = 0) -> list[list[str]]:
        """First ``n`` records, column order as in ``meta.column_names``.

        With ``max_bytes`` at most that much CSV is read; more raises ``DataTooLarge``.
        """
        if n <= 0:
            return []
        rows, truncated = self.qsv.slice_checked(self.csv_path, 0, n, max_bytes=max(max_bytes, 0))
        if truncated:
            raise DataTooLarge(f"the first {n} rows hold more than {max_bytes} bytes of data")
        return [self._normalize_row(r) for r in rows]

    def iter_rows(self, limit: int | None = None, max_bytes: int = 0) -> Iterator[list[str]]:
        """Stream all records (or the first ``limit``) without loading the file.

        With ``max_bytes``, records past that many bytes (``row_bytes``) raise ``DataTooLarge``.
        """
        size = 0
        with self.csv_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.reader(fh)
            next(reader, None)  # header
            for i, row in enumerate(reader):
                if limit is not None and i >= limit:
                    break
                if max_bytes > 0:
                    size += row_bytes(row)
                    if size > max_bytes:
                        raise DataTooLarge(f"the rows hold more than {max_bytes} bytes of data")
                yield self._normalize_row(row)

    def iter_chunks(
        self, chunk_size: int, limit: int | None = None, max_bytes: int = 0
    ) -> Iterator[tuple[int, list[list[str]]]]:
        """Yield ``(start_index, rows)`` chunks."""
        chunk: list[list[str]] = []
        start = 0
        for i, row in enumerate(self.iter_rows(limit, max_bytes)):
            chunk.append(row)
            if len(chunk) >= chunk_size:
                yield start, chunk
                start = i + 1
                chunk = []
        if chunk:
            yield start, chunk

    def page(self, offset: int, n: int) -> list[list[str]]:
        """Up to ``n`` records from ``offset`` for a response held in memory.

        The row count is lowered so rows x columns stays within
        ``settings.max_preview_cells``, and at most ``settings.max_preview_bytes`` of
        CSV is read, so a very wide upload or very long cells give fewer rows rather than
        an unbounded response.
        """
        n_cols = max(len(self.meta.column_names), 1)
        if settings.max_preview_cells > 0:
            n = min(n, settings.max_preview_cells // n_cols)
        if n <= 0:
            return []
        rows = self.qsv.slice(self.csv_path, offset, n, max_bytes=max(settings.max_preview_bytes, 0))
        return [self._normalize_row(r) for r in rows]

    def preview(self, n: int) -> list[dict[str, str]]:
        names = self.meta.column_names
        return [dict(zip(names, row)) for row in self.page(0, n)]
