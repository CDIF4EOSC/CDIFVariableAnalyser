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
    default_max_rows: int = 5
    chunk_size: int = 500
    upload_ttl_seconds: int = 6 * 3600
    api_key: str | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Statistics (qsv stats / qsv frequency). ``stats_everything_max_bytes`` is the
    # cut-off above which ``--everything`` is skipped: it loads and sorts every
    # numeric column in memory, so median, quartiles, mode and cardinality are
    # dropped for very large uploads rather than risking an OOM.
    stats_timeout: float = 120.0
    stats_everything_max_bytes: int = 256 * 1024 * 1024
    stats_category_limit: int = 25

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


settings = Settings()
