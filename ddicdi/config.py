"""Runtime settings for the gen2 backend.

All values can be overridden with environment variables prefixed ``DDI_``
(for example ``DDI_QSV_BIN=/usr/local/bin/qsv``) or a ``.env`` file.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _default_qsv_bin() -> str:
    bundled = PROJECT_ROOT / "bin" / "qsv"
    if bundled.exists():
        return str(bundled)
    found = shutil.which("qsv")
    return found or str(bundled)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DDI_", env_file=".env", extra="ignore")

    qsv_bin: str = _default_qsv_bin()
    work_dir: Path = Path(tempfile.gettempdir()) / "ddicdi-gen2"

    # Import limits (security #1). ``qsv_timeout`` is the wall-clock limit of every qsv
    # call that passes no timeout of its own; the child is killed when it elapses.
    # ``import_max_bytes`` caps the size of any file a qsv child writes (RLIMIT_FSIZE),
    # so a small compressed .zsav/.parquet cannot expand into an unbounded data.csv.
    # ``qsv_max_memory_bytes`` caps the child's address space (RLIMIT_AS); it is off by
    # default because jemalloc/Polars reserve far more virtual memory than they use, but
    # is worth setting on Linux deployments after checking real files still convert.
    # 0 switches a limit off.
    qsv_timeout: float = 300.0
    import_max_bytes: int = 2 * 1024**3
    qsv_max_memory_bytes: int = 0
    max_upload_bytes: int = 512 * 1024**2
    max_concurrent_imports: int = 2
    default_max_rows: int = 5
    chunk_size: int = 500
    upload_ttl_seconds: int = 6 * 3600
    api_key: str | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Size limits of a generated document (DDI-CDI and CDIF). Every attribute variable
    # qualifies every measure, so ``qualifies`` grows as attributes x measures; both are
    # checked before generation and a request over either limit gets a 400.
    max_variables: int = 20_000
    max_qualifies_refs: int = 1_000_000

    # Statistics (qsv stats / qsv frequency). ``stats_everything_max_bytes`` is the
    # cut-off above which ``--everything`` is skipped: it loads and sorts every
    # numeric column in memory, so median, quartiles, mode and cardinality are
    # dropped for very large uploads rather than risking an OOM.
    stats_timeout: float = 120.0
    stats_everything_max_bytes: int = 256 * 1024 * 1024
    stats_category_limit: int = 25

    # Editing limits. ``max_cell_chars`` caps one cell (32767 is SPSS's longest string).
    # ``edit_max_csv_bytes`` caps a rewritten data.csv; ``work_dir_max_bytes`` caps all
    # uploads together (0 = no work-dir cap). Edits that would pass a cap are refused.
    max_cell_chars: int = 32767
    edit_max_csv_bytes: int = 2 * 1024**3
    work_dir_max_bytes: int = 20 * 1024**3

    # AI enrichment via n8n webhooks (shared with the SoGreen provenance editor).
    # ``n8n_bearer_key`` is the full ``Authorization`` header value; empty = feature off.
    n8n_unit_url: str = ""
    n8n_concept_url: str = ""
    # Variable role (measure / identifier / attribute) workflow, n8n id PYUwqzBoczLFXhYk.
    n8n_role_url: str = ""
    # Variable function (Weight, UnitIdentifier, ...) workflow, n8n id 9OQwmjQcvhIMputR.
    n8n_function_url: str = ""
    # Level of measurement (nominal / ordinal / scale) workflow, n8n id tuRgtz0JyOeUYr9i.
    n8n_measure_url: str = ""
    n8n_bearer_key: str = ""
    n8n_timeout: float = 120.0
    n8n_concurrency: int = 5

    # Most data cells (rows x variables) one generated document may carry. Every cell
    # becomes an InstanceValue, a DataPoint and a DataPointPosition, held in memory and
    # serialised in one piece: about 5.4 KB of peak memory per cell, so the default
    # keeps one request near 1.3 GB on the 3.5 GB App Service B2 plan. Larger requests
    # are refused with 413; 0 or less turns the limit off.
    max_output_cells: int = 250_000


settings = Settings()
