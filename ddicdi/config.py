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
    # Admission control (security #7). A request that finds every import (or document
    # build) slot taken waits without holding a worker thread, but at most
    # ``max_queued_requests`` wait per limiter and none longer than ``queue_timeout``
    # seconds; the rest get a 503 with Retry-After at once.
    max_queued_requests: int = 8
    queue_timeout: float = 60.0
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

    # Bounds on what one variable may carry (GitLab #8, #12). Every path that makes or
    # changes a variable checks them: import, the edit API, Open from QLever. A name is
    # at most 64 characters (SPSS's limit). A value-label code becomes part of four to
    # six element ids, so it is at most ``max_code_chars``; a variable has at most
    # ``max_value_labels`` labelled codes and ``max_missing_ranges`` missing ranges, and a
    # variable or value label is at most ``max_label_chars``. qsv output read for
    # metadata (sniff, headers, stats, readstat metadata) is at most
    # ``qsv_max_output_bytes``; a file whose metadata is larger is refused.
    max_name_chars: int = 64
    max_code_chars: int = 1000
    max_value_labels: int = 10_000
    max_missing_ranges: int = 100
    max_label_chars: int = 4000
    qsv_max_output_bytes: int = 32 * 1024**2
    # A print format (``F8.2``, ``%9.0g``) or storage type (``double``) is at most this
    # long (GitLab #19).
    max_format_chars: int = 64

    # Statistics (qsv stats / qsv frequency). ``stats_everything_max_bytes`` is the
    # cut-off above which ``--everything`` is skipped: it loads and sorts every
    # numeric column in memory, so median, quartiles, mode and cardinality are
    # dropped for very large uploads rather than risking an OOM.
    stats_timeout: float = 120.0
    stats_everything_max_bytes: int = 256 * 1024 * 1024
    stats_category_limit: int = 25
    # Statistics and edits whose work grows with the upload (GitLab #13) run under
    # admission control like imports: at most ``max_concurrent_heavy`` at once, the rest
    # queue (``max_queued_requests``, ``queue_timeout``) or get a 503. Requests on one
    # upload that change it, or read what an edit is rewriting, take turns.
    max_concurrent_heavy: int = 4

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
    # Bounds on enrichment (security #11): variables per request (the editor splits
    # larger selections), enrich requests running at once in the process, and the wall
    # clock of one request; calls still outstanding then are cancelled.
    max_enrich_variables: int = 200
    max_concurrent_enrich: int = 2
    enrich_deadline: float = 900.0

    # Most data cells (rows x variables) one generated document may carry. Every cell
    # becomes an InstanceValue, a DataPoint and a DataPointPosition, held in memory and
    # serialised in one piece: about 5.4 KB of peak memory per cell, so the default
    # keeps one request near 1.3 GB on the 3.5 GB App Service B2 plan. Larger requests
    # are refused with 413; 0 or less turns the limit off. The limit is also the budget
    # shared by every build in flight (security #8), so concurrent requests cannot add up
    # past it; ``max_concurrent_builds`` caps how many builds run at once.
    max_output_cells: int = 250_000

    # Row previews (preview, file info, upload): rows x columns and bytes of CSV per
    # response (security #9). A wide upload or long cells give fewer rows. 0 = off.
    max_preview_cells: int = 50_000
    max_preview_bytes: int = 4 * 1024**2
    max_concurrent_builds: int = 4
    # Bytes of CSV data one document build may read (GitLab #12): rows are counted as
    # cells, so long cells are charged by their bytes as well. 0 = off.
    max_output_data_bytes: int = 64 * 1024**2

    # Every element of a generated document is named ``urn:uuid:<uuid>`` (cdi/ids.py).
    # ``readable_ids`` keeps the symbolic ``#instanceVariable-age`` ids instead, for
    # teaching examples and debugging. A save to QLever always uses UUIDs.
    readable_ids: bool = False

    # QLever store for "Save to QLever" / "Import from QLever" (QLever-deployment repo).
    # Empty URL = feature off. The token is QLever's ACCESS_TOKEN: it guards writes only;
    # reads are open to whoever reaches the port, so keep QLever on a private network.
    # ``cdif_shacl_shapes``: CDIF SHACL shapes to check a save against (warnings only);
    # default the vendored ddicdi/cdif/shapes/CDIF-Complete-Shapes.ttl.
    qlever_url: str = ""
    qlever_access_token: str = ""
    qlever_timeout: float = 60.0
    cdif_shacl_shapes: Path | None = None
    # SHACL validation of a CDIF document (Check, Save to QLever; GitLab #10) runs in a
    # child process, at most ``max_concurrent_validations`` at once, stopped after
    # ``shacl_timeout`` seconds; a graph of more than ``shacl_max_triples`` triples is
    # reported as not checked.
    max_concurrent_validations: int = 1
    # Reading a saved document back (download, Open in the editor; GitLab #18): at most
    # ``qlever_max_document_bytes`` of N-Triples from QLever, parsed off the event loop,
    # ``max_concurrent_qlever_reads`` at once. A workspace opened from a document has a
    # meta.json of at most ``max_meta_bytes`` (GitLab #20).
    qlever_max_document_bytes: int = 64 * 1024**2
    max_concurrent_qlever_reads: int = 2
    max_meta_bytes: int = 64 * 1024**2
    shacl_timeout: float = 120.0
    shacl_max_triples: int = 500_000


settings = Settings()
