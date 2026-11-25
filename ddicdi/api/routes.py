"""REST endpoints."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .. import __version__, editing, enrich, limits, qlever, saved_statistics, stats, vocabularies
from ..cdi.ids import IdMap, assign_ids
from ..cdi.jsonld import GenerateOptions, build_document
from ..cdif import convert_document, dataset_header
from ..cdif.reverse import NotADocument, document_to_meta
from ..images.cdif import is_image_graph
from ..cdi.statistics import STATISTIC_NAMES
from ..config import settings
from ..data import Dataset, DataTooLarge
from ..importers import SUPPORTED_EXTENSIONS
from ..qsv import QsvError
from ..roles import ROLE_NAMES, parse_roles
from .schemas import (
    CategoryStatsOut,
    CellsIn,
    DatasetInfoIO,
    EnrichErrorOut,
    EnrichIn,
    EnrichOut,
    EnrichSuggestion,
    FileInfo,
    GenerateRequest,
    HealthOut,
    NewVariableIn,
    OutputRequest,
    QleverDocumentOut,
    QleverSaveOut,
    ShaclOut,
    RolesIn,
    StatisticsOut,
    VariableOut,
    VariablePatchIn,
)
from . import admission
from .store import MetadataTooLarge, StorageFull, UploadNotFound, UploadStore

router = APIRouter(prefix="/api")

# DDI-CDI JSON-LD, or the same document converted to CDIF.
OutputFormat = Literal["ddicdi", "cdif"]


def get_store(request: Request) -> UploadStore:
    return request.app.state.store


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


def _download(jsonld: str, filename: str, suffix: str = "_DDICDI.jsonld") -> Response:
    base = Path(filename).stem
    return Response(
        content=jsonld.encode("utf-8"),
        media_type="application/ld+json",
        headers={"Content-Disposition": f'attachment; filename="{base}{suffix}"'},
    )


def _load(store: UploadStore, file_id: str) -> Dataset:
    try:
        return store.load(file_id)
    except UploadNotFound:
        raise HTTPException(status_code=404, detail=f"Unknown file_id {file_id}")


def _save(store: UploadStore, file_id: str, dataset: Dataset) -> None:
    editing.ensure_roles(dataset.meta)
    store.save_meta(file_id, dataset.meta)
    editing.touch(dataset.csv_path.parent)


def _apply_roles(dataset: Dataset, req: GenerateRequest) -> None:
    """The roles of a generate request, or the stored ones."""
    if req.roles:
        try:
            dataset.meta.roles = parse_roles(dataset.meta, req.roles)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        editing.ensure_roles(dataset.meta)


def _render(dataset: Dataset, req: GenerateRequest | OutputRequest, fmt: OutputFormat) -> str:
    return _cdif(dataset, req) if fmt == "cdif" else _jsonld(dataset, req)


def _rows(dataset: Dataset, req: GenerateRequest | OutputRequest, fmt: OutputFormat = "ddicdi") -> int:
    """The data rows a build is admitted for; the builder reads no more (GitLab #14)."""
    if fmt == "cdif":
        return 0  # CDIF carries no data rows
    meta = dataset.meta
    return meta.number_rows if req.process_all_rows else min(req.max_rows, meta.number_rows)


def _data_bytes(dataset: Dataset, rows: int) -> int:
    """Bytes of CSV data a build of ``rows`` rows may read (GitLab #12); 0 = no limit.

    All rows may hold the whole data.csv. A first-rows build may hold twice the average
    share of its rows (at least 256 KB), so a file with unusually long cells at the top
    gets a 413 rather than a build larger than it was charged for.
    """
    limit = settings.max_output_data_bytes
    if rows <= 0 or limit <= 0:
        return 0
    try:
        size = dataset.csv_path.stat().st_size
    except OSError:
        size = 0
    total = max(dataset.meta.number_rows, 1)
    share = size if rows >= total else max(2 * size * rows // total, 256 * 1024)
    return max(min(share, limit), 1)


def _metadata_cost(dataset: Dataset) -> int:
    n_vars = max(len(dataset.meta.variables), 1)
    return admission.VARIABLE_COST * n_vars + admission.CODE_COST * limits.code_count(dataset.meta)


def _build_cost(dataset: Dataset, req: GenerateRequest | OutputRequest, fmt: OutputFormat) -> int:
    """Estimated size of the document in data cells (see ``admission.builds``): the
    cells, the variables and labelled codes, and the bytes of data it may read."""
    n_vars = max(len(dataset.meta.variables), 1)
    rows = _rows(dataset, req, fmt)
    data = _data_bytes(dataset, rows) // admission.DATA_BYTES_PER_UNIT
    return rows * n_vars + _metadata_cost(dataset) + data


async def _render_admitted(dataset: Dataset, req: GenerateRequest | OutputRequest, fmt: OutputFormat, render=None):
    """Build the document off the event loop, holding its size in the shared build budget.

    An oversized request is refused (413) before it queues; the rest wait for room
    without holding a worker thread, so the memory of all builds in flight is bounded.
    """
    _check_output_size(dataset, req, fmt)
    async with admission.builds.slot(_build_cost(dataset, req, fmt)):
        return await run_in_threadpool(render or _render, dataset, req, fmt)


async def _generate(store: UploadStore, file_id: str, req: GenerateRequest, fmt: OutputFormat = "ddicdi") -> Response:
    dataset = await run_in_threadpool(_load, store, file_id)
    _apply_roles(dataset, req)
    content = await _render_admitted(dataset, req, fmt)
    return _download(content, dataset.meta.datafile, "_CDIF.json" if fmt == "cdif" else "_DDICDI.jsonld")


def _check_output_size(dataset: Dataset, req: GenerateRequest | OutputRequest, fmt: OutputFormat = "ddicdi") -> None:
    """Refuse a request whose document would not fit in memory (``max_output_cells``).

    Every included cell is built as several JSON-LD objects in one in-memory document,
    so the row count a caller asks for is bounded here before any of it is built. The
    variables and labelled codes count too (GitLab #12): every format has them.
    """
    limit = settings.max_output_cells
    if limit <= 0:
        return
    meta = dataset.meta
    n_vars = max(len(meta.variables), 1)
    rows = _rows(dataset, req, fmt)
    if rows * n_vars > limit:
        raise HTTPException(
            status_code=413,
            detail=(
                f"The output would hold {rows:,} rows x {n_vars:,} variables = {rows * n_vars:,} data cells; "
                f"the limit is {limit:,}. Ask for at most {limit // n_vars:,} rows, or 0 rows for metadata only."
            ),
        )
    if _metadata_cost(dataset) > limit:
        raise HTTPException(
            status_code=413,
            detail=(
                f"The document's {len(meta.variables):,} variables and {limits.code_count(meta):,} value labels "
                f"are more than one document may hold (limit {limit:,} units)."
            ),
        )


def _jsonld_doc(dataset: Dataset, req: GenerateRequest | OutputRequest) -> tuple[dict, IdMap]:
    """The DDI-CDI document for a generate or output request, every node named by a UUID."""
    _check_output_size(dataset, req)
    rows = _rows(dataset, req)
    doc = _stats(  # statistics are the only part that can fail on a bad weight or qsv
        build_document,
        dataset,
        spssfile=dataset.meta.datafile,
        options=GenerateOptions(
            max_rows=req.max_rows,
            process_all_rows=req.process_all_rows,
            chunk_size=settings.chunk_size,
            include_statistics=req.include_statistics,
            statistics_weight=req.statistics_weight,
            statistics_include=req.statistics_include,
            # No more rows, and no more data, than _build_cost charged for, whatever
            # data.csv holds by now (GitLab #12, #14).
            row_limit=rows,
            max_data_bytes=_data_bytes(dataset, rows),
        ),
    )
    return assign_ids(doc, dataset.meta, readable=settings.readable_ids)


def _cdif_doc(
    dataset: Dataset, req: GenerateRequest | OutputRequest, readable: bool | None = None
) -> tuple[dict, IdMap]:
    """The document converted to CDIF: metadata only, so no data rows; statistics when asked
    for. Every node is named by a UUID; the dataset's own IRI is its record IRI."""
    doc = _stats(  # statistics are the only part that can fail on a bad weight or qsv
        build_document,
        dataset,
        options=GenerateOptions(
            max_rows=0,
            include_statistics=req.include_statistics,
            statistics_weight=req.statistics_weight,
            statistics_include=req.statistics_include,
        ),
    )
    # The dataset description from the editor goes in as the header the converter reads.
    doc.update(dataset_header(dataset.meta))
    meta = dataset.meta
    record = meta.info.record_id.strip() or f"urn:uuid:{meta.doc_uuid}"
    cdif = convert_document(doc, Path(meta.datafile).stem, explicit_id=record)
    readable = settings.readable_ids if readable is None else readable
    return assign_ids(cdif, meta, base_iri=record, readable=readable)


def _jsonld(dataset: Dataset, req: GenerateRequest | OutputRequest) -> str:
    return json.dumps(_jsonld_doc(dataset, req)[0], indent=4, ensure_ascii=False)


def _cdif(dataset: Dataset, req: GenerateRequest | OutputRequest) -> str:
    return json.dumps(_cdif_doc(dataset, req)[0], indent=2, ensure_ascii=False)


# -- info -----------------------------------------------------------------------------


@router.get("/health", response_model=HealthOut)
def health(store: UploadStore = Depends(get_store)) -> HealthOut:
    try:
        qsv_version = store.qsv.version().split(" ")[1].split("-")[0]
    except Exception:
        qsv_version = None
    return HealthOut(status="healthy", version=__version__, service="DDI-CDI Converter API", qsv=qsv_version)


@router.get("/info")
def info() -> dict:
    return {
        "service": "DDI-CDI Converter API",
        "version": __version__,
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
        "output_format": "application/ld+json",
        "output_formats": {"ddicdi": "DDI-CDI 1.1beta JSON-LD (default)", "cdif": "CDIF JSON-LD, converted from DDI-CDI"},
        "roles": list(ROLE_NAMES),
        "statistics": list(STATISTIC_NAMES),
        "endpoints": {
            "POST /api/files": "upload a file; returns metadata and preview",
            "GET /api/files/{id}": "metadata again",
            "GET /api/files/{id}/preview?rows=N": "first N rows",
            "POST /api/files/{id}/generate?format=ddicdi|cdif": "generate DDI-CDI (or CDIF) JSON-LD as a download",
            "POST /api/files/{id}/output?format=ddicdi|cdif": "regenerate for the editor preview (JSON-LD as JSON)",
            "PUT /api/files/{id}/roles": "replace all variable roles",
            "GET|PUT /api/files/{id}/info": "dataset description (title, creators, contributors, publisher, dates, keywords, licence, identifier, coverage, funding) for the CDIF output",
            "POST /api/files/{id}/variables": "add a variable (new column)",
            "PATCH /api/files/{id}/variables/{name}": "edit label, format, type, measure, value labels, missing, role, functions, name, unit of measure, concepts",
            "GET /api/files/{id}/statistics": "summary statistics per variable (qsv stats); also emitted into the output with include_statistics",
            "GET /api/files/{id}/statistics/{name}/categories": "frequency distribution of one variable (qsv frequency)",
            "POST /api/files/{id}/enrich": "AI suggestions (unit of measure, ELSST concepts, variable role, variable function, level of measurement) via n8n; nothing is saved until PATCHed",
            "DELETE /api/files/{id}/variables/{name}": "remove a variable",
            "PATCH /api/files/{id}/rows/{index}": "edit cells of one row",
            "POST /api/files/{id}/rows": "append a row",
            "DELETE /api/files/{id}/rows/{index}": "remove a row",
            "DELETE /api/files/{id}": "remove upload",
            "POST /api/convert": "one-shot upload + generate (compatible with the original API); output_format=cdif for CDIF",
            "POST /api/files/{id}/cdif/check": "check the CDIF against the CDIF SHACL shapes (nothing is saved)",
            "POST /api/files/{id}/qlever": "save the CDIF to QLever (one named graph per document, replaced on re-save)",
            "GET /api/qlever/documents": "documents saved to QLever (from its catalog graph)",
            "GET /api/qlever/documents/{uuid}?format=jsonld|turtle": "one saved document read back from QLever",
            "POST /api/qlever/documents/{uuid}/open": "open a saved document in the editor (metadata only, no data rows)",
        },
        "authentication": "X-API-Key header" if settings.api_key else "none",
        "ai_enrichment": bool(settings.n8n_bearer_key),
        "qlever": qlever.configured(),
        "vocabularies": vocabularies.as_json(),
    }


# -- session style --------------------------------------------------------------------

async def _read_upload(file: UploadFile) -> bytes:
    """The upload's bytes; 413 as soon as it exceeds ``settings.max_upload_bytes``."""
    limit = settings.max_upload_bytes
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(1 << 20):
        size += len(chunk)
        if limit and size > limit:
            raise HTTPException(status_code=413, detail=f"Upload larger than the limit of {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


async def _create(store: UploadStore, file: UploadFile):
    """Read and import an upload holding an import slot (see :mod:`.admission`).

    The slot is taken before the body is read, so queued uploads stay in Starlette's
    spooled temp file rather than in memory, and waiting holds no worker thread. The
    import itself runs off the event loop, so other requests are served while qsv runs.
    """
    async with admission.imports.slot():
        content = await _read_upload(file)
        try:
            return await run_in_threadpool(store.create, file.filename or "upload", content)
        except StorageFull as exc:
            raise HTTPException(status_code=507, detail=f"Could not import file: {exc}")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not import file: {exc}")


@router.post("/files", response_model=FileInfo, dependencies=[Depends(require_api_key)])
async def upload(
    file: UploadFile = File(...),
    preview_rows: int = Query(settings.default_max_rows, ge=0, le=1000),
    store: UploadStore = Depends(get_store),
) -> FileInfo:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type {ext!r}")
    file_id, dataset = await _create(store, file)
    store.cleanup_expired()
    rows = await run_in_threadpool(dataset.preview, preview_rows)
    return FileInfo.from_meta(file_id, dataset.meta, rows)


@router.get("/files/{file_id}", response_model=FileInfo, dependencies=[Depends(require_api_key)])
def file_info(
    file_id: str, preview_rows: int = Query(0, ge=0, le=1000), store: UploadStore = Depends(get_store)
) -> FileInfo:
    dataset = _load(store, file_id)
    return FileInfo.from_meta(file_id, dataset.meta, dataset.preview(preview_rows))


@router.get("/files/{file_id}/preview", dependencies=[Depends(require_api_key)])
def preview(
    file_id: str,
    rows: int = Query(5, ge=0, le=10000),
    offset: int = Query(0, ge=0),
    store: UploadStore = Depends(get_store),
) -> dict:
    dataset = _load(store, file_id)
    data = dataset.page(offset, rows)
    return {
        "columns": dataset.meta.column_names,
        "rows": data,
        "offset": offset,
        "total_rows": dataset.meta.number_rows,
    }


@router.post("/files/{file_id}/generate", dependencies=[Depends(require_api_key)])
async def generate(
    file_id: str,
    req: GenerateRequest,
    format: OutputFormat = Query("ddicdi", description="ddicdi (default) or cdif"),
    store: UploadStore = Depends(get_store),
) -> Response:
    return await _generate(store, file_id, req, format)


@router.post("/files/{file_id}/output", dependencies=[Depends(require_api_key)])
async def output(
    file_id: str,
    req: OutputRequest,
    format: OutputFormat = Query("ddicdi", description="ddicdi (default) or cdif"),
    variable_ids: bool = Query(False, description="wrap the document with the element IRIs of each variable"),
    store: UploadStore = Depends(get_store),
) -> Response:
    """Editor preview: the current document with the stored roles, not as a download.

    With ``variable_ids`` the answer is ``{"document": ..., "variable_ids": {name: [IRI, ...]}}``:
    the element IRIs are UUIDs, so the editor cannot tell from them which variable an
    element belongs to.
    """
    dataset = await run_in_threadpool(_load, store, file_id)
    editing.ensure_roles(dataset.meta)
    if not variable_ids:
        content = await _render_admitted(dataset, req, format)
        return Response(content=content, media_type="application/ld+json")

    def render(ds: Dataset, r: OutputRequest, fmt: OutputFormat) -> str:
        doc, ids = _cdif_doc(ds, r) if fmt == "cdif" else _jsonld_doc(ds, r)
        index = {name: sorted(iris) for name, iris in ids.by_variable.items()}
        return json.dumps({"document": doc, "variable_ids": index}, ensure_ascii=False)

    content = await _render_admitted(dataset, req, format, render)
    return Response(content=content, media_type="application/json")


# -- editing -----------------------------------------------------------------------------


def _edit(fn, *args):
    try:
        return fn(*args)
    except editing.EditError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:  # e.g. ENOSPC; the rewrite has already removed its temp file
        raise HTTPException(status_code=507, detail=f"Edit failed, the server could not store the data: {exc.strerror or exc}")


def _var_out(dataset: Dataset, name: str) -> VariableOut:
    info = FileInfo.from_meta("", dataset.meta, [])
    return next(v for v in info.variables if v.name == name)


async def _locked(file_id: str, fn, *args, heavy: bool = False):
    """Run ``fn(*args)`` off the event loop holding the upload's lock (GitLab #14).

    Edits are read-modify-write cycles over meta.json and data.csv, so the ones on one
    upload take turns. ``heavy`` work (a rewrite of data.csv, statistics) also holds a
    slot of ``admission.heavy``, so only a few run at once across all uploads; waiting
    for either holds no worker thread (GitLab #13).
    """
    async with admission.uploads.hold(file_id):
        if not heavy:
            return await run_in_threadpool(fn, *args)
        async with admission.heavy.slot():
            return await run_in_threadpool(fn, *args)


@router.put("/files/{file_id}/roles", response_model=FileInfo, dependencies=[Depends(require_api_key)])
async def put_roles(file_id: str, body: RolesIn, store: UploadStore = Depends(get_store)) -> FileInfo:
    def run() -> FileInfo:
        dataset = _load(store, file_id)
        _edit(editing.set_roles, dataset.meta, body.roles)
        _save(store, file_id, dataset)
        return FileInfo.from_meta(file_id, dataset.meta, [])

    return await _locked(file_id, run)


@router.get("/files/{file_id}/info", response_model=DatasetInfoIO, dependencies=[Depends(require_api_key)])
def get_dataset_info(file_id: str, store: UploadStore = Depends(get_store)) -> DatasetInfoIO:
    return DatasetInfoIO.from_info(_load(store, file_id).meta.info)


@router.put("/files/{file_id}/info", response_model=DatasetInfoIO, dependencies=[Depends(require_api_key)])
async def put_dataset_info(file_id: str, body: DatasetInfoIO, store: UploadStore = Depends(get_store)) -> DatasetInfoIO:
    def run() -> DatasetInfoIO:
        dataset = _load(store, file_id)
        dataset.meta.info = body.to_info()
        _save(store, file_id, dataset)
        return DatasetInfoIO.from_info(dataset.meta.info)

    return await _locked(file_id, run)


@router.post(
    "/files/{file_id}/variables", response_model=VariableOut, status_code=201, dependencies=[Depends(require_api_key)]
)
async def add_variable(file_id: str, body: NewVariableIn, store: UploadStore = Depends(get_store)) -> VariableOut:
    def run() -> VariableOut:
        dataset = _load(store, file_id)
        spec = editing.NewVariable(
            name=body.name,
            label=body.label,
            format=body.format,
            storage_type=body.type,
            measure=body.measure,
            value_labels=body.value_labels,
            missing=body.missing,
            role=body.role,
            fill=body.fill,
            fill_value=body.fill_value,
            position=body.position,
            unit_of_measure=body.unit_of_measure,
            concepts=body.concepts,
            functions=body.functions,
        )
        var = _edit(editing.add_variable, dataset, spec)
        _save(store, file_id, dataset)
        return _var_out(dataset, var.name)

    return await _locked(file_id, run, heavy=True)  # rewrites data.csv


@router.patch("/files/{file_id}/variables/{name}", response_model=VariableOut, dependencies=[Depends(require_api_key)])
async def patch_variable(
    file_id: str, name: str, body: VariablePatchIn, store: UploadStore = Depends(get_store)
) -> VariableOut:
    def run() -> VariableOut:
        dataset = _load(store, file_id)
        patch = editing.VariablePatch(
            label=body.label,
            format=body.format,
            storage_type=body.type,
            measure=body.measure,
            value_labels=body.value_labels,
            missing=body.missing,
            role=body.role,
            unit_of_measure=body.unit_of_measure,
            concepts=body.concepts,
            functions=body.functions,
        )
        var = _edit(editing.update_variable, dataset.meta, name, patch)
        if body.new_name is not None and body.new_name != name:
            var = _edit(editing.rename_variable, dataset, name, body.new_name)
        _save(store, file_id, dataset)
        return _var_out(dataset, var.name)

    renames = body.new_name is not None and body.new_name != name
    return await _locked(file_id, run, heavy=renames)  # a rename rewrites data.csv


@router.delete("/files/{file_id}/variables/{name}", response_model=FileInfo, dependencies=[Depends(require_api_key)])
async def delete_variable(file_id: str, name: str, store: UploadStore = Depends(get_store)) -> FileInfo:
    def run() -> FileInfo:
        dataset = _load(store, file_id)
        _edit(editing.delete_variable, dataset, name)
        _save(store, file_id, dataset)
        return FileInfo.from_meta(file_id, dataset.meta, [])

    return await _locked(file_id, run, heavy=True)


@router.patch("/files/{file_id}/rows/{index}", dependencies=[Depends(require_api_key)])
async def patch_row(file_id: str, index: int, body: CellsIn, store: UploadStore = Depends(get_store)) -> dict:
    def run() -> dict:
        dataset = _load(store, file_id)
        row = _edit(editing.update_cells, dataset, index, body.values)
        _save(store, file_id, dataset)
        return {"index": index, "row": dataset._normalize_row(row), "total_rows": dataset.meta.number_rows}

    return await _locked(file_id, run, heavy=True)


@router.post("/files/{file_id}/rows", status_code=201, dependencies=[Depends(require_api_key)])
async def add_row(file_id: str, body: CellsIn | None = None, store: UploadStore = Depends(get_store)) -> dict:
    def run() -> dict:
        dataset = _load(store, file_id)
        index = _edit(editing.append_row, dataset, body.values if body else {})
        _save(store, file_id, dataset)
        return {"index": index, "total_rows": dataset.meta.number_rows}

    # An append is cheap, but it must not race another edit's count of the rows.
    return await _locked(file_id, run)


@router.delete("/files/{file_id}/rows/{index}", dependencies=[Depends(require_api_key)])
async def delete_row(file_id: str, index: int, store: UploadStore = Depends(get_store)) -> dict:
    def run() -> dict:
        dataset = _load(store, file_id)
        _edit(editing.delete_row, dataset, index)
        _save(store, file_id, dataset)
        return {"total_rows": dataset.meta.number_rows}

    return await _locked(file_id, run, heavy=True)


@router.delete("/files/{file_id}", status_code=204, dependencies=[Depends(require_api_key)])
def delete_file(file_id: str, store: UploadStore = Depends(get_store)) -> Response:
    try:
        store.delete(file_id)
    except UploadNotFound:
        raise HTTPException(status_code=404, detail=f"Unknown file_id {file_id}")
    return Response(status_code=204)


# -- statistics (the editor's tables; the document gets them via include_statistics) ------


def _stats(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DataTooLarge as exc:
        raise HTTPException(
            status_code=413,
            detail=f"The output would read more data than one document may hold: {exc}. Ask for fewer rows.",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except QsvError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/files/{file_id}/statistics", response_model=StatisticsOut, dependencies=[Depends(require_api_key)])
async def statistics(
    file_id: str,
    weight: str | None = Query(None, description='Weight variable, or "auto" for the first Weight-function one'),
    refresh: bool = Query(False, description="Recompute even when qsv's cache is current"),
    store: UploadStore = Depends(get_store),
) -> StatisticsOut:
    dataset = await run_in_threadpool(_load, store, file_id)
    saved = saved_statistics.load(dataset.meta)
    if saved is not None:  # a session opened from QLever: no data, the saved numbers
        out = StatisticsOut.from_domain(file_id, saved.summary, dataset.meta)
        out.saved = True
        return out

    def run() -> StatisticsOut:
        current = _load(store, file_id)  # as it is now that no edit runs on it
        result = _stats(stats.summary_stats, current, weight=weight, force=refresh)
        return StatisticsOut.from_domain(file_id, result, current.meta)

    # qsv stats over the whole file: admitted like an import, and runs on one upload
    # take turns (they share qsv's cache file) (GitLab #13).
    return await _locked(file_id, run, heavy=True)


@router.get(
    "/files/{file_id}/statistics/{name}/categories",
    response_model=CategoryStatsOut,
    dependencies=[Depends(require_api_key)],
)
async def categories(
    file_id: str,
    name: str,
    limit: int = Query(settings.stats_category_limit, ge=1, le=10000),
    weight: str | None = Query(None),
    sort: Literal["count", "code"] = Query("count"),
    store: UploadStore = Depends(get_store),
) -> CategoryStatsOut:
    dataset = await run_in_threadpool(_load, store, file_id)
    if name not in set(dataset.meta.column_names):
        raise HTTPException(status_code=404, detail=f"Unknown variable {name!r}")
    if saved_statistics.active(dataset.meta):
        found = saved_statistics.category(dataset.meta, name, limit=limit, sort=sort)
        if found is None:
            raise HTTPException(status_code=404, detail=f"The saved document has no frequencies for {name!r}")
        return CategoryStatsOut.from_domain(found)

    def run() -> CategoryStatsOut:
        current = _load(store, file_id)
        if name not in set(current.meta.column_names):
            raise HTTPException(status_code=404, detail=f"Unknown variable {name!r}")
        result = _stats(stats.category_stats, current, name, limit=limit, weight=weight, sort=sort)
        return CategoryStatsOut.from_domain(result)

    return await _locked(file_id, run, heavy=True)  # qsv frequency over the whole file


# -- AI enrichment (suggestions only; the client PATCHes what it accepts) -----------------


@router.post("/files/{file_id}/enrich", response_model=EnrichOut, dependencies=[Depends(require_api_key)])
async def enrich_variables(file_id: str, body: EnrichIn, store: UploadStore = Depends(get_store)) -> EnrichOut:
    if not body.kinds:
        raise HTTPException(status_code=400, detail="kinds must not be empty")
    limit = settings.max_enrich_variables
    # The request list is refused before any per-item work, repeated names included
    # (GitLab #15).
    if limit > 0 and body.variables is not None and len(body.variables) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{len(body.variables)} variables in one enrich request; the limit is {limit}. Send them in parts.",
        )
    dataset = await run_in_threadpool(_load, store, file_id)
    variables = dataset.meta.variables
    if body.variables is not None:
        known = {v.name for v in variables}
        unknown = [n for n in dict.fromkeys(body.variables) if n not in known]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown variables: {unknown[:50]}")
        wanted = set(body.variables)
        variables = [v for v in variables if v.name in wanted]
    if limit > 0 and len(variables) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{len(variables)} variables in one enrich request; the limit is {limit}. Send them in parts.",
        )
    try:
        async with admission.enrichments.slot():
            result = await enrich.enrich(variables, body.kinds)
    except enrich.NotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except enrich.EnrichError as exc:
        raise HTTPException(status_code=504, detail=str(exc))
    if result.errors and not result.suggestions:
        raise HTTPException(status_code=502, detail=f"n8n enrichment failed: {result.errors[0]['message']}")
    return EnrichOut(
        suggestions=[EnrichSuggestion(**s) for s in result.suggestions.values()],
        errors=[EnrichErrorOut(**e) for e in result.errors],
    )


# -- one-shot, compatible with the original api.py ---------------------------------------


@router.post("/convert", dependencies=[Depends(require_api_key)])
async def convert_once(
    file: UploadFile = File(...),
    max_rows: int = Form(5),
    process_all_rows: str = Form("false"),
    variable_roles: str | None = Form(None),
    include_statistics: str = Form("false"),
    statistics_weight: str | None = Form(None),
    statistics_include: str | None = Form(None, description="Comma separated; omitted = every statistic"),
    output_format: str = Form("ddicdi", description="ddicdi (default) or cdif"),
    store: UploadStore = Depends(get_store),
) -> Response:
    roles: dict[str, str] = {}
    if variable_roles:
        try:
            roles = json.loads(variable_roles)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"variable_roles is not valid JSON: {exc}")
    if output_format not in ("ddicdi", "cdif"):
        raise HTTPException(status_code=400, detail=f"Unknown output_format {output_format!r}; use ddicdi or cdif")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type {ext!r}")
    file_id, _ = await _create(store, file)
    try:
        try:
            req = GenerateRequest(
                roles=roles,
                max_rows=max_rows,
                process_all_rows=str(process_all_rows).lower() == "true",
                include_statistics=str(include_statistics).lower() == "true",
                statistics_weight=statistics_weight or None,
                statistics_include=(
                    [name.strip() for name in statistics_include.split(",") if name.strip()]
                    if statistics_include
                    else None
                ),
            )
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc.errors()[0]["msg"]))
        return await _generate(store, file_id, req, output_format)
    finally:
        store.delete(file_id)


# -- QLever store ---------------------------------------------------------------------
# Design: QLever-deployment/grilling-summary.md. Save converts the editor's document to
# CDIF and replaces its named graph; Import reads a saved graph back for viewing and
# download (it does not open an editor session).


def _qlever_call(exc: qlever.QleverError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


def _claim_record_iri(store: UploadStore, file_id: str) -> Dataset:
    """The dataset with a record IRI kept in the workspace. An empty one, or the
    ``urn:ddi-cdi:<stem>`` that imports wrote before documents had UUIDs (not unique: two
    uploads of one file share it), becomes ``urn:uuid:<doc_uuid>``; one the user entered
    is kept."""
    dataset = _load(store, file_id)
    meta = dataset.meta
    if not meta.info.record_id.strip() or meta.info.record_id.startswith(qlever.PLACEHOLDER_RECORD_PREFIX):
        meta.info.record_id = qlever.graph_iri(meta.doc_uuid)
        _save(store, file_id, dataset)
    return dataset


def _cdif_graph(dataset: Dataset, req: OutputRequest) -> tuple[dict, "qlever.Graph"]:
    """The CDIF of the document (always UUIDs: relative ids would clash across graphs)
    and its RDF graph."""
    cdif = _cdif_doc(dataset, req, readable=False)[0]
    return cdif, qlever.cdif_graph(cdif)


@asynccontextmanager
async def _cdif_admitted(dataset: Dataset, req: OutputRequest):
    """Hold a build slot sized for the CDIF and its RDF graph for the whole of a check or
    save: the document, the graph, the SHACL validation and the upload (GitLab #10)."""
    _check_output_size(dataset, req, "cdif")
    async with admission.builds.slot(_build_cost(dataset, req, "cdif") * admission.RDF_FACTOR):
        yield


async def _shacl(graph) -> dict:
    """SHACL validation: a few at once, each in a child process with a deadline."""
    async with admission.validations.slot():
        return await run_in_threadpool(qlever.shacl_check, graph)


@router.post("/files/{file_id}/cdif/check", response_model=ShaclOut, dependencies=[Depends(require_api_key)])
async def check_cdif(file_id: str, req: OutputRequest | None = None, store: UploadStore = Depends(get_store)) -> ShaclOut:
    """Validate the CDIF of this document against the CDIF SHACL shapes, as a save to
    QLever would, without saving anything. Needs no QLever."""
    req = req or OutputRequest(max_rows=0)
    dataset = await run_in_threadpool(_load, store, file_id)
    editing.ensure_roles(dataset.meta)
    async with _cdif_admitted(dataset, req):
        _, graph = await run_in_threadpool(_cdif_graph, dataset, req)
        shacl = await _shacl(graph)
        del graph
    return ShaclOut(**shacl, missing_required=qlever.missing_required(dataset.meta.info, dataset.meta.datafile))


@router.post("/files/{file_id}/qlever", response_model=QleverSaveOut, dependencies=[Depends(require_api_key)])
async def save_to_qlever(
    file_id: str, request: Request, req: OutputRequest | None = None, store: UploadStore = Depends(get_store)
) -> QleverSaveOut:
    """Save the CDIF of this document to QLever, replacing what an earlier save stored.

    SHACL problems are reported, not refused (testing phase).
    """
    if not qlever.configured():
        raise HTTPException(status_code=503, detail="QLever is not configured on this server (DDI_QLEVER_URL)")
    req = req or OutputRequest(max_rows=0)
    dataset = await _locked(file_id, _claim_record_iri, store, file_id)
    doc_uuid = dataset.meta.doc_uuid
    async with _cdif_admitted(dataset, req):
        cdif, graph = await run_in_threadpool(_cdif_graph, dataset, req)
        dataset_iri = cdif["@id"]
        if not qlever.is_absolute_iri(dataset_iri):
            raise HTTPException(
                status_code=400,
                detail=f"The record IRI {dataset_iri!r} is not an absolute IRI; fix it in the Dataset tab or clear it",
            )
        shacl = await _shacl(graph)
        entry = qlever.CatalogEntry(
            uuid=doc_uuid,
            title=str(cdif.get("schema:name") or dataset.meta.datafile),
            dataset_iri=dataset_iri,
            source_file=dataset.meta.datafile,
            triples=len(graph),
            saved_at=qlever.now_iso(),
            # Set by App Service authentication when it is switched on.
            saved_by=request.headers.get("x-ms-client-principal-name", ""),
        )
        del cdif
        try:
            await qlever.put_graph(entry.graph, graph)  # serialises off the event loop
            await qlever.write_catalog_entry(entry)
        except qlever.QleverError as exc:
            raise _qlever_call(exc)
        del graph
    return QleverSaveOut(
        uuid=doc_uuid,
        graph=entry.graph,
        dataset_iri=dataset_iri,
        triples=entry.triples,
        saved_at=entry.saved_at,
        info=DatasetInfoIO.from_info(dataset.meta.info),
        shacl=ShaclOut(**shacl, missing_required=qlever.missing_required(dataset.meta.info, dataset.meta.datafile)),
    )


@router.get("/qlever/documents", response_model=list[QleverDocumentOut], dependencies=[Depends(require_api_key)])
async def list_qlever_documents() -> list[QleverDocumentOut]:
    try:
        return [QleverDocumentOut(**d) for d in await qlever.list_catalog()]
    except qlever.QleverError as exc:
        raise _qlever_call(exc)


@router.post("/qlever/documents/{doc_uuid}/open", response_model=FileInfo, dependencies=[Depends(require_api_key)])
async def open_qlever_document(doc_uuid: str, store: UploadStore = Depends(get_store)) -> FileInfo:
    """Open a saved document in the editor: a metadata-only session rebuilt from its CDIF.

    There is no data file behind it (the Data and Statistics tabs are empty), and what
    CDIF does not carry is lost (see ``cdif/reverse.py``). The session keeps the
    document's UUID, so its next save replaces the same graph.

    The read is bounded in bytes, parsed and mapped off the event loop, and only a few
    run at once (GitLab #18); the workspace counts against the work-dir quota (#20).
    """
    if not qlever.is_uuid(doc_uuid):
        raise HTTPException(status_code=400, detail="Not a document UUID")
    graph_name = qlever.graph_iri(doc_uuid)
    async with admission.qlever_reads.slot():
        try:
            graph = await qlever.construct_graph(graph_name)
        except qlever.QleverError as exc:
            raise _qlever_call(exc)
        if not len(graph):
            raise HTTPException(status_code=404, detail=f"No document {doc_uuid} in QLever")

        if is_image_graph(graph):
            raise HTTPException(status_code=409, detail="This document is an image record; open it as an image (POST /api/images/from-qlever/{uuid})")

        def build() -> tuple[str, FileInfo]:
            try:
                meta = document_to_meta(qlever.restore_numeric_types(graph), doc_uuid, graph_name)
            except NotADocument as exc:
                raise HTTPException(status_code=422, detail=str(exc))
            try:
                limits.check_meta(meta)  # the same limits as an import (GitLab #12)
            except limits.LimitError as exc:
                raise HTTPException(status_code=413, detail=f"The document cannot be opened: {exc}")
            editing.ensure_roles(meta)
            try:
                file_id = store.create_from_meta(meta)
            except StorageFull as exc:
                raise HTTPException(status_code=507, detail=f"Could not open the document: {exc}")
            except MetadataTooLarge as exc:
                raise HTTPException(status_code=413, detail=f"Could not open the document: {exc}")
            try:
                return file_id, FileInfo.from_meta(file_id, meta, [])
            except Exception:
                store.delete(file_id)  # nothing is left behind (GitLab #20)
                raise

        _, info = await run_in_threadpool(build)
    return info


@router.get("/qlever/documents/{doc_uuid}", dependencies=[Depends(require_api_key)])
async def get_qlever_document(
    doc_uuid: str,
    format: Literal["jsonld", "turtle"] = Query("jsonld", description="jsonld (default) or turtle"),
    download: bool = Query(False, description="as an attachment"),
) -> Response:
    """One saved document as stored: flat compact JSON-LD (or Turtle), numeric types restored.

    Bounded and off the event loop like Open (GitLab #18)."""
    if not qlever.is_uuid(doc_uuid):
        raise HTTPException(status_code=400, detail="Not a document UUID")
    async with admission.qlever_reads.slot():
        try:
            graph = await qlever.construct_graph(qlever.graph_iri(doc_uuid))
        except qlever.QleverError as exc:
            raise _qlever_call(exc)
        if not len(graph):
            raise HTTPException(status_code=404, detail=f"No document {doc_uuid} in QLever")

        def render() -> tuple[bytes, str, str]:
            restored = qlever.restore_numeric_types(graph)
            if format == "turtle":
                return qlever.to_turtle(restored).encode("utf-8"), "text/turtle", ".ttl"
            body = json.dumps(qlever.to_jsonld(restored), indent=2, ensure_ascii=False)
            return body.encode("utf-8"), "application/ld+json", "_CDIF.jsonld"

        body, media, suffix = await run_in_threadpool(render)
    headers = {"Content-Disposition": f'attachment; filename="{doc_uuid}{suffix}"'} if download else {}
    return Response(content=body, media_type=media, headers=headers)
