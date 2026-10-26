"""REST endpoints."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, Response, UploadFile
from pydantic import ValidationError

from .. import __version__, editing, enrich, stats
from ..cdi.jsonld import GenerateOptions, build_document, generate_complete_json_ld
from ..cdif import convert_document
from ..cdi.statistics import STATISTIC_NAMES
from ..config import settings
from ..data import Dataset
from ..importers import SUPPORTED_EXTENSIONS
from ..qsv import QsvError
from ..roles import ROLE_NAMES, parse_roles
from .schemas import (
    CategoryStatsOut,
    CellsIn,
    EnrichErrorOut,
    EnrichIn,
    EnrichOut,
    EnrichSuggestion,
    FileInfo,
    GenerateRequest,
    HealthOut,
    NewVariableIn,
    OutputRequest,
    RolesIn,
    StatisticsOut,
    VariableOut,
    VariablePatchIn,
)
from .store import UploadNotFound, UploadStore

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


def _generate(store: UploadStore, file_id: str, req: GenerateRequest, fmt: OutputFormat = "ddicdi") -> Response:
    dataset = _load(store, file_id)
    if req.roles:
        try:
            dataset.meta.roles = parse_roles(dataset.meta, req.roles)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    else:
        editing.ensure_roles(dataset.meta)
    if fmt == "cdif":
        return _download(_cdif(dataset), dataset.meta.datafile, "_CDIF.json")
    return _download(_jsonld(dataset, req), dataset.meta.datafile)


def _jsonld(dataset: Dataset, req: GenerateRequest | OutputRequest) -> str:
    """The JSON-LD document for a generate or output request."""
    return _stats(  # statistics are the only part that can fail on a bad weight or qsv
        generate_complete_json_ld,
        dataset,
        spssfile=dataset.meta.datafile,
        max_rows=req.max_rows,
        process_all_rows=req.process_all_rows,
        chunk_size=settings.chunk_size,
        include_statistics=req.include_statistics,
        statistics_weight=req.statistics_weight,
        statistics_include=req.statistics_include,
    )


def _cdif(dataset: Dataset) -> str:
    """The document converted to CDIF. CDIF is metadata only, so no rows or statistics go in."""
    doc = build_document(dataset, options=GenerateOptions(max_rows=0))
    cdif = convert_document(doc, Path(dataset.meta.datafile).stem)
    return json.dumps(cdif, indent=2, ensure_ascii=False)


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
        },
        "authentication": "X-API-Key header" if settings.api_key else "none",
        "ai_enrichment": bool(settings.n8n_bearer_key),
    }


# -- session style --------------------------------------------------------------------


@router.post("/files", response_model=FileInfo, dependencies=[Depends(require_api_key)])
async def upload(
    file: UploadFile = File(...),
    preview_rows: int = Query(settings.default_max_rows, ge=0, le=1000),
    store: UploadStore = Depends(get_store),
) -> FileInfo:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type {ext!r}")
    content = await file.read()
    try:
        file_id, dataset = store.create(file.filename or "upload", content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not import file: {exc}")
    store.cleanup_expired()
    return FileInfo.from_meta(file_id, dataset.meta, dataset.preview(preview_rows))


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
    if offset:
        data = [dataset._normalize_row(r) for r in dataset.qsv.slice(dataset.csv_path, offset, rows)] if rows else []
    else:
        data = dataset.head(rows)
    return {
        "columns": dataset.meta.column_names,
        "rows": data,
        "offset": offset,
        "total_rows": dataset.meta.number_rows,
    }


@router.post("/files/{file_id}/generate", dependencies=[Depends(require_api_key)])
def generate(
    file_id: str,
    req: GenerateRequest,
    format: OutputFormat = Query("ddicdi", description="ddicdi (default) or cdif"),
    store: UploadStore = Depends(get_store),
) -> Response:
    return _generate(store, file_id, req, format)


@router.post("/files/{file_id}/output", dependencies=[Depends(require_api_key)])
def output(
    file_id: str,
    req: OutputRequest,
    format: OutputFormat = Query("ddicdi", description="ddicdi (default) or cdif"),
    store: UploadStore = Depends(get_store),
) -> Response:
    """Editor preview: the current document with the stored roles, not as a download."""
    dataset = _load(store, file_id)
    editing.ensure_roles(dataset.meta)
    content = _cdif(dataset) if format == "cdif" else _jsonld(dataset, req)
    return Response(content=content, media_type="application/ld+json")


# -- editing -----------------------------------------------------------------------------


def _edit(fn, *args):
    try:
        return fn(*args)
    except editing.EditError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _var_out(dataset: Dataset, name: str) -> VariableOut:
    info = FileInfo.from_meta("", dataset.meta, [])
    return next(v for v in info.variables if v.name == name)


@router.put("/files/{file_id}/roles", response_model=FileInfo, dependencies=[Depends(require_api_key)])
def put_roles(file_id: str, body: RolesIn, store: UploadStore = Depends(get_store)) -> FileInfo:
    dataset = _load(store, file_id)
    _edit(editing.set_roles, dataset.meta, body.roles)
    _save(store, file_id, dataset)
    return FileInfo.from_meta(file_id, dataset.meta, [])


@router.post(
    "/files/{file_id}/variables", response_model=VariableOut, status_code=201, dependencies=[Depends(require_api_key)]
)
def add_variable(file_id: str, body: NewVariableIn, store: UploadStore = Depends(get_store)) -> VariableOut:
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


@router.patch("/files/{file_id}/variables/{name}", response_model=VariableOut, dependencies=[Depends(require_api_key)])
def patch_variable(file_id: str, name: str, body: VariablePatchIn, store: UploadStore = Depends(get_store)) -> VariableOut:
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


@router.delete("/files/{file_id}/variables/{name}", response_model=FileInfo, dependencies=[Depends(require_api_key)])
def delete_variable(file_id: str, name: str, store: UploadStore = Depends(get_store)) -> FileInfo:
    dataset = _load(store, file_id)
    _edit(editing.delete_variable, dataset, name)
    _save(store, file_id, dataset)
    return FileInfo.from_meta(file_id, dataset.meta, [])


@router.patch("/files/{file_id}/rows/{index}", dependencies=[Depends(require_api_key)])
def patch_row(file_id: str, index: int, body: CellsIn, store: UploadStore = Depends(get_store)) -> dict:
    dataset = _load(store, file_id)
    row = _edit(editing.update_cells, dataset, index, body.values)
    _save(store, file_id, dataset)
    return {"index": index, "row": dataset._normalize_row(row), "total_rows": dataset.meta.number_rows}


@router.post("/files/{file_id}/rows", status_code=201, dependencies=[Depends(require_api_key)])
def add_row(file_id: str, body: CellsIn | None = None, store: UploadStore = Depends(get_store)) -> dict:
    dataset = _load(store, file_id)
    index = _edit(editing.append_row, dataset, body.values if body else {})
    _save(store, file_id, dataset)
    return {"index": index, "total_rows": dataset.meta.number_rows}


@router.delete("/files/{file_id}/rows/{index}", dependencies=[Depends(require_api_key)])
def delete_row(file_id: str, index: int, store: UploadStore = Depends(get_store)) -> dict:
    dataset = _load(store, file_id)
    _edit(editing.delete_row, dataset, index)
    _save(store, file_id, dataset)
    return {"total_rows": dataset.meta.number_rows}


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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except QsvError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/files/{file_id}/statistics", response_model=StatisticsOut, dependencies=[Depends(require_api_key)])
def statistics(
    file_id: str,
    weight: str | None = Query(None, description='Weight variable, or "auto" for the first Weight-function one'),
    refresh: bool = Query(False, description="Recompute even when qsv's cache is current"),
    store: UploadStore = Depends(get_store),
) -> StatisticsOut:
    dataset = _load(store, file_id)
    result = _stats(stats.summary_stats, dataset, weight=weight, force=refresh)
    return StatisticsOut.from_domain(file_id, result, dataset.meta)


@router.get(
    "/files/{file_id}/statistics/{name}/categories",
    response_model=CategoryStatsOut,
    dependencies=[Depends(require_api_key)],
)
def categories(
    file_id: str,
    name: str,
    limit: int = Query(settings.stats_category_limit, ge=1, le=10000),
    weight: str | None = Query(None),
    sort: Literal["count", "code"] = Query("count"),
    store: UploadStore = Depends(get_store),
) -> CategoryStatsOut:
    dataset = _load(store, file_id)
    if name not in dataset.meta.column_names:
        raise HTTPException(status_code=404, detail=f"Unknown variable {name!r}")
    result = _stats(stats.category_stats, dataset, name, limit=limit, weight=weight, sort=sort)
    return CategoryStatsOut.from_domain(result)


# -- AI enrichment (suggestions only; the client PATCHes what it accepts) -----------------


@router.post("/files/{file_id}/enrich", response_model=EnrichOut, dependencies=[Depends(require_api_key)])
async def enrich_variables(file_id: str, body: EnrichIn, store: UploadStore = Depends(get_store)) -> EnrichOut:
    dataset = _load(store, file_id)
    variables = dataset.meta.variables
    if body.variables is not None:
        unknown = [n for n in body.variables if n not in dataset.meta.column_names]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Unknown variables: {unknown}")
        wanted = set(body.variables)
        variables = [v for v in variables if v.name in wanted]
    if not body.kinds:
        raise HTTPException(status_code=400, detail="kinds must not be empty")
    try:
        result = await enrich.enrich(variables, body.kinds)
    except enrich.NotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
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
    content = await file.read()
    try:
        file_id, _ = store.create(file.filename or "upload", content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not import file: {exc}")
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
        return _generate(store, file_id, req, output_format)  # type: ignore[arg-type]
    finally:
        store.delete(file_id)
