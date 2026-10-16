"""Thin wrapper around the qsv command line tool.

qsv (https://github.com/dathere/qsv) does all the heavy lifting: reading
SPSS/Stata/SAS files (``qsv readstat``), sniffing CSV files and slicing or
counting the cached CSV. Nothing in this module parses statistical files
itself.
"""

from __future__ import annotations

import csv
import io
import json
import os
import subprocess
from pathlib import Path

from .config import settings

READSTAT_EXTENSIONS = {".sav", ".zsav", ".por", ".dta", ".sas7bdat", ".xpt", ".xpt5", ".xpt8"}
# Formats whose reader keeps user-missing codes with ``--sentinels-as`` (qsv#4667). qsv
# refuses the option for Stata (until qsv#4627 is fixed upstream), .por and .xpt.
SENTINEL_EXTENSIONS = {".sav", ".zsav", ".sas7bdat"}


class QsvError(RuntimeError):
    """qsv exited with a non-zero status."""


class Qsv:
    def __init__(self, binary: str | os.PathLike[str] | None = None) -> None:
        self.binary = str(binary or settings.qsv_bin)
        self._supports_sentinels: bool | None = None
        if not Path(self.binary).exists():
            raise FileNotFoundError(
                f"qsv binary not found at {self.binary!r}. Set DDI_QSV_BIN or place qsv in bin/."
            )

    # -- generic -----------------------------------------------------------------

    def run(self, *args: str, input_bytes: bytes | None = None, timeout: float | None = None) -> bytes:
        env = dict(os.environ, QSV_PROGRESSBAR="0", QSV_NO_UPDATE="1")
        try:
            proc = subprocess.run(
                [self.binary, *args],
                input=input_bytes,
                capture_output=True,
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise QsvError(f"qsv {' '.join(args)} timed out after {timeout}s")
        if proc.returncode != 0:
            raise QsvError(
                f"qsv {' '.join(args)} failed ({proc.returncode}): "
                f"{proc.stderr.decode('utf-8', 'replace').strip()}"
            )
        return proc.stdout

    def version(self) -> str:
        return self.run("--version").decode().strip()

    def has_command(self, name: str) -> bool:
        listing = self.run("--list").decode()
        return any(line.split()[:1] == [name] for line in listing.splitlines())

    # -- readstat ---------------------------------------------------------------

    def readstat_metadata(self, path: str | os.PathLike[str]) -> dict:
        out = self.run("readstat", "--metadata", "json", str(path))
        return json.loads(out)

    @property
    def supports_sentinels(self) -> bool:
        """Whether this qsv build has ``readstat --sentinels-as`` (after 23.0.1)."""
        if self._supports_sentinels is None:
            self._supports_sentinels = b"--sentinels-as" in self.run("readstat", "--help")
        return self._supports_sentinels

    def readstat_to_csv(
        self, path: str | os.PathLike[str], out_path: str | os.PathLike[str], *, keep_sentinels: bool = False
    ) -> None:
        """Convert to CSV. ``keep_sentinels`` writes user-missing codes (SPSS 99, SAS .R)
        into their own column instead of leaving the cell empty."""
        args = ["--sentinels-as", "value", "--sentinels-embedded"] if keep_sentinels else []
        self.run("readstat", *args, str(path), "-o", str(out_path))

    # -- parquet ----------------------------------------------------------------

    def parquet_to_csv(self, path: str | os.PathLike[str], out_path: str | os.PathLike[str]) -> None:
        """Convert a Parquet file to CSV with ``qsv sqlp`` (Polars)."""
        literal = str(path).replace("'", "''")
        self.run("sqlp", "SKIP_INPUT", f"SELECT * FROM read_parquet('{literal}')", "-o", str(out_path))

    # -- csv --------------------------------------------------------------------

    def sniff(self, path: str | os.PathLike[str]) -> dict:
        out = self.run("sniff", "--json", str(path))
        return json.loads(out)

    def normalize_csv(
        self, path: str | os.PathLike[str], out_path: str | os.PathLike[str], delimiter: str = ","
    ) -> None:
        """Rewrite any delimited file as a standard comma separated, quoted CSV."""
        args = ["input"]
        if delimiter != ",":
            args += ["-d", delimiter]
        args += [str(path), "-o", str(out_path)]
        self.run(*args)

    def count(self, csv_path: str | os.PathLike[str]) -> int:
        return int(self.run("count", str(csv_path)).decode().strip())

    def headers(self, csv_path: str | os.PathLike[str]) -> list[str]:
        out = self.run("headers", "--just-names", str(csv_path)).decode()
        return [line for line in out.splitlines() if line != ""]

    def column_types(self, csv_path: str | os.PathLike[str]) -> list[str]:
        """Per-column data types via ``qsv stats --typesonly``.

        Returns qsv's type names in column order (``Integer``, ``Float``, ``String``,
        ``Date``, ``DateTime``, ``Boolean``, ``NULL``). Dates are inferred for every
        column, not just those whose name matches qsv's default date whitelist.
        """
        out = self.run(
            "stats",
            str(csv_path),
            "--typesonly",
            "--infer-dates",
            "--dates-whitelist",
            "all",
            "--jsonl",
        ).decode("utf-8")
        return [json.loads(line)["type"] for line in out.splitlines() if line.strip()]

    def column_profiles(self, csv_path: str | os.PathLike[str]) -> list[dict]:
        """Per-column type plus the pieces of ``qsv stats`` a print format needs.

        Each dict has ``field``, ``type`` and, when qsv reports them, ``min``, ``max``
        (as strings), ``max_length`` (strings) and ``max_precision`` (floats). Dates
        are inferred for every column, like :meth:`column_types`.
        """
        out = self.run(
            "stats",
            str(csv_path),
            "--infer-dates",
            "--dates-whitelist",
            "all",
            "--jsonl",
        ).decode("utf-8")
        keep = ("field", "type", "min", "max", "max_length", "max_precision")
        return [
            {k: d[k] for k in keep if k in d}
            for d in (json.loads(line) for line in out.splitlines() if line.strip())
        ]

    def slice(self, csv_path: str | os.PathLike[str], start: int = 0, length: int = 5) -> list[list[str]]:
        """Return ``length`` records starting at 0-based ``start`` (header excluded)."""
        if length <= 0:
            return []
        out = self.run("slice", "--start", str(start), "--len", str(length), str(csv_path))
        rows = list(csv.reader(io.StringIO(out.decode("utf-8"))))
        return rows[1:]  # drop header

    # -- statistics -----------------------------------------------------------------

    def stats(
        self,
        csv_path: str | os.PathLike[str],
        *,
        weight: str | None = None,
        everything: bool = True,
        round_to: int = 4,
        cache_threshold: int = 1,
        mode_cardinality_cap: int = 100_000,
        force: bool = False,
        timeout: float | None = None,
    ) -> list[dict]:
        """``qsv stats --jsonl``: one dict per column.

        ``cache_threshold=1`` makes qsv keep its own ``<stem>.stats.csv`` next to the
        input, which it reuses until the CSV is touched again. ``--stats-jsonl`` is
        deliberately not passed; qsv rejects it together with ``--jsonl``.
        """
        args = [
            "stats",
            str(csv_path),
            "--jsonl",
            "--round",
            str(round_to),
            "-c",
            str(cache_threshold),
            "--mode-cardinality-cap",
            str(mode_cardinality_cap),
        ]
        if everything:
            args.append("--everything")
        if weight:
            args += ["--weight", weight]
        if force:
            args.append("--force")
        out = self.run(*args, timeout=timeout).decode("utf-8")
        return [json.loads(line) for line in out.splitlines() if line.strip()]

    def frequency(
        self,
        csv_path: str | os.PathLike[str],
        *,
        select: list[int] | None = None,
        limit: int = 25,
        unq_limit: int = 10,
        weight: str | None = None,
        timeout: float | None = None,
    ) -> dict:
        """``qsv frequency --json`` for the given 1-based column indices.

        Indices rather than names: qsv's select syntax needs escaping for names with
        commas or dashes, and the caller already knows the column order.
        ``--no-nulls`` keeps percentages as valid percentages and keeps the NULL
        bucket out of ``cardinality``; the missing count comes from ``nullcount``.
        """
        args = ["frequency", str(csv_path)]
        if select:
            args += ["-s", ",".join(str(i) for i in select)]
        args += [
            "--limit",
            str(limit),
            "--unq-limit",
            str(unq_limit),
            "--json",
            "--no-stats",
            "--no-nulls",
        ]
        if weight:
            args += ["--weight", weight]
        return json.loads(self.run(*args, timeout=timeout))
