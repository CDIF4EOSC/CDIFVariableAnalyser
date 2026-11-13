"""Per-upload working directories: original file, cached data.csv and meta.json."""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path

from ..config import settings
from ..data import Dataset
from ..editing import work_dir_usage
from ..importers import import_file
from ..models import DatasetMeta
from ..qsv import Qsv


class UploadNotFound(KeyError):
    pass


class StorageFull(OSError):
    """The work directory has no room for the upload under ``work_dir_max_bytes``."""


class UploadStore:
    def __init__(self, root: Path, ttl_seconds: int, qsv: Qsv | None = None) -> None:
        self.root = Path(root)
        self.ttl = ttl_seconds
        self._qsv = qsv
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def qsv(self) -> Qsv:
        if self._qsv is None:
            self._qsv = Qsv()
        return self._qsv

    def _dir(self, file_id: str) -> Path:
        if not file_id.isalnum():
            raise UploadNotFound(file_id)
        return self.root / file_id

    def create(self, filename: str, content: bytes) -> tuple[str, Dataset]:
        # Reclaim expired uploads first, so a full disk can recover even when this
        # upload then fails to write.
        try:
            self.cleanup_expired()
        except Exception:
            pass
        quota = settings.work_dir_max_bytes
        if quota > 0 and work_dir_usage(self.root) + len(content) > quota:
            raise StorageFull(f"the server's upload storage is full (limit {quota} bytes); try again later")
        file_id = uuid.uuid4().hex
        d = self._dir(file_id)
        d.mkdir(parents=True)
        safe_name = Path(filename).name or "upload"
        src = d / f"source{Path(safe_name).suffix.lower()}"
        try:
            src.write_bytes(content)
            dataset = import_file(src, d, self.qsv, datafile=safe_name)
            n_vars = len(dataset.meta.variables)
            if settings.max_variables > 0 and n_vars > settings.max_variables:
                raise ValueError(f"the file has {n_vars} variables; the limit is {settings.max_variables}")
            # The expanded data.csv (and the source) now count; imports running at the
            # same time see each other's files, so the cap is passed by at most the
            # imports in flight.
            self.save_meta(file_id, dataset.meta)
            if quota > 0 and work_dir_usage(self.root) > quota:
                raise StorageFull(
                    f"the imported data does not fit in the server's upload storage (limit {quota} bytes)"
                )
        except Exception:
            shutil.rmtree(d, ignore_errors=True)
            raise
        return file_id, dataset

    def save_meta(self, file_id: str, meta: DatasetMeta) -> None:
        d = self._dir(file_id)
        (d / "meta.json").write_text(json.dumps(meta.to_dict(), ensure_ascii=False))
        self._touch(d)

    @staticmethod
    def _touch(d: Path) -> None:
        """Refresh the directory mtime that ``cleanup_expired`` reads, so the TTL counts
        from the last use of an upload, not from the upload itself. Rewriting a file
        inside the directory does not change the directory's own mtime."""
        try:
            os.utime(d)
        except OSError:
            pass

    def load(self, file_id: str) -> Dataset:
        d = self._dir(file_id)
        meta_path = d / "meta.json"
        if not meta_path.exists():
            raise UploadNotFound(file_id)
        self._touch(d)
        meta = DatasetMeta.from_dict(json.loads(meta_path.read_text()))
        return Dataset(meta, d / "data.csv", self.qsv)

    def delete(self, file_id: str) -> None:
        d = self._dir(file_id)
        if not d.exists():
            raise UploadNotFound(file_id)
        shutil.rmtree(d, ignore_errors=True)

    def cleanup_expired(self) -> int:
        now = time.time()
        removed = 0
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return 0
        for d in entries:
            try:
                if d.is_dir() and now - d.stat().st_mtime > self.ttl:
                    shutil.rmtree(d, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        return removed
