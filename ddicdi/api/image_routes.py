"""REST endpoints of image collections: CDIF metadata for images (``/api/images``).

Upload images (one or many), describe each with the vision model (staged as a
suggestion the user accepts or rejects), edit the shared bundle defaults and each
image's own fields, check against the CDIF shapes, and download a zip with one CDIF
file per image.
"""

from __future__ import annotations

import io
import zipfile
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import qlever
from ..config import settings
from ..enrich import EnrichError, NotConfigured
from ..images import describe as ai
from ..images.cdif import cdif_filename, dumps, image_cdif
from ..images.collection import (
    CollectionFull,
    CollectionNotFound,
    ImageCollection,
    ImageItem,
    ImageStore,
    StorageFull,
    Suggestion,
    effective_info,
)
from ..images.media import ImageRejected, iso_day, process
from . import admission
from .routes import require_api_key
from .schemas import _LIST_MAX, _TEXT_MAX, _TITLE_MAX, DatasetInfoIO, ShaclOut, ShortStr

router = APIRouter(prefix="/api/images", tags=["images"], dependencies=[Depends(require_api_key)])


def get_images(request: Request) -> ImageStore:
    return request.app.state.images


# -- schemas --------------------------------------------------------------------------


class SuggestionIO(BaseModel):
    title: str = Field("", max_length=_TITLE_MAX)
    description: str = Field("", max_length=_TEXT_MAX)
    keywords: list[ShortStr] = Field(default_factory=list, max_length=_LIST_MAX)


class ImageOut(BaseModel):
    id: str
    filename: str
    mime: str
    width: int
    height: int
    size: int
    md5: str
    info: DatasetInfoIO = Field(description="the image's own fields; empty ones inherit from the bundle")
    effective: DatasetInfoIO = Field(description="what the CDIF is written from: own fields plus the bundle")
    ai_status: str
    ai_error: str = ""
    suggestion: SuggestionIO | None = None
    thumb_url: str
    preview_url: str

    @classmethod
    def build(cls, coll: ImageCollection, item: ImageItem) -> "ImageOut":
        base = f"/api/images/{coll.uid}/items/{item.uid}"
        return cls(
            id=item.uid,
            filename=item.filename,
            mime=item.mime,
            width=item.width,
            height=item.height,
            size=item.size,
            md5=item.md5,
            info=DatasetInfoIO.from_info(item.info),
            effective=DatasetInfoIO.from_info(effective_info(coll.bundle, item)),
            ai_status=item.ai_status,
            ai_error=item.ai_error,
            suggestion=SuggestionIO(**item.suggestion.__dict__) if item.suggestion else None,
            thumb_url=f"{base}/thumb.jpg",
            preview_url=f"{base}/preview.jpg",
        )


class RejectedOut(BaseModel):
    filename: str
    reason: str


class CollectionOut(BaseModel):
    id: str
    bundle: DatasetInfoIO
    images: list[ImageOut]
    rejected: list[RejectedOut] = Field(default_factory=list, description="uploads of this request that were refused")
    max_images: int
    ai_configured: bool

    @classmethod
    def build(cls, coll: ImageCollection, rejected: list[RejectedOut] | None = None) -> "CollectionOut":
        return cls(
            id=coll.uid,
            bundle=DatasetInfoIO.from_info(coll.bundle),
            images=[ImageOut.build(coll, i) for i in coll.images],
            rejected=rejected or [],
            max_images=settings.max_images,
            ai_configured=bool(settings.n8n_bearer_key),
        )


class ImageCheckOut(BaseModel):
    id: str
    filename: str
    shacl: ShaclOut


# -- helpers --------------------------------------------------------------------------


def _load(images: ImageStore, collection_id: str) -> ImageCollection:
    try:
        return images.load(collection_id)
    except CollectionNotFound:
        raise HTTPException(status_code=404, detail="Image collection not found or expired")


def _item(coll: ImageCollection, image_id: str) -> ImageItem:
    try:
        return coll.image(image_id)
    except CollectionNotFound:
        raise HTTPException(status_code=404, detail="Image not found in this collection")


async def _read(file: UploadFile) -> bytes:
    limit = settings.max_image_bytes
    chunks, size = [], 0
    while chunk := await file.read(1 << 20):
        size += len(chunk)
        if limit and size > limit:
            raise ImageRejected(f"{file.filename!r} is larger than the limit of {limit} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


# The browser's last-modified day of each file, in upload order (a File's lastModified).
LastModified = Annotated[
    list[str] | None,
    Form(description="YYYY-MM-DD last-modified day of each file, in the order of files; optional"),
]


async def _add_files(
    images: ImageStore, collection_id: str, files: list[UploadFile], last_modified: list[str] | None = None
) -> CollectionOut:
    """Decode and store each upload; a bad file is reported, the others are kept."""
    if settings.max_images > 0 and len(files) > settings.max_images:
        raise HTTPException(status_code=400, detail=f"At most {settings.max_images} images per collection")
    rejected: list[RejectedOut] = []
    async with admission.imports.slot():
        processed = []
        days = last_modified or []
        for n, f in enumerate(files):
            name = f.filename or "image"
            modified = iso_day(days[n][:10]) if n < len(days) else ""
            try:
                content = await _read(f)
                processed.append((name, await run_in_threadpool(process, content, name), modified))
            except ImageRejected as exc:
                rejected.append(RejectedOut(filename=name, reason=str(exc)))

    def store() -> ImageCollection:
        coll = _load(images, collection_id)
        for name, p, modified in processed:
            try:
                images.add(coll, name, p, modified)
            except CollectionFull as exc:
                rejected.append(RejectedOut(filename=name, reason=str(exc)))
            except StorageFull as exc:
                images.save(coll)
                raise HTTPException(status_code=507, detail=str(exc))
        images.default_bundle_dates(coll)
        images.save(coll)
        return coll

    async with admission.uploads.hold(collection_id):
        coll = await run_in_threadpool(store)
    return CollectionOut.build(coll, rejected)


async def _change(images: ImageStore, collection_id: str, fn):
    """Read-modify-write of a collection, one at a time per collection."""

    def run():
        coll = _load(images, collection_id)
        out = fn(coll)
        images.save(coll)
        return out

    async with admission.uploads.hold(collection_id):
        return await run_in_threadpool(run)


# -- collection -----------------------------------------------------------------------


@router.post("", response_model=CollectionOut, status_code=201)
async def create_collection(
    files: Annotated[list[UploadFile], File(description="JPEG, PNG, WebP or TIFF images")],
    last_modified: LastModified = None,
    images: ImageStore = Depends(get_images),
) -> CollectionOut:
    """A new collection holding the uploaded images. Refused files are listed in
    ``rejected``; when every file is refused, nothing is created (400)."""
    if settings.max_images > 0 and len(files) > settings.max_images:
        raise HTTPException(status_code=400, detail=f"At most {settings.max_images} images per collection")
    coll = await run_in_threadpool(images.create)
    try:
        out = await _add_files(images, coll.uid, files, last_modified)
    except Exception:
        await run_in_threadpool(images.delete, coll.uid)
        raise
    if not out.images:
        await run_in_threadpool(images.delete, coll.uid)
        reasons = "; ".join(r.reason for r in out.rejected) or "no images"
        raise HTTPException(status_code=400, detail=f"No image could be read: {reasons}")
    return out


@router.get("/{collection_id}", response_model=CollectionOut)
def get_collection(collection_id: str, images: ImageStore = Depends(get_images)) -> CollectionOut:
    return CollectionOut.build(_load(images, collection_id))


@router.delete("/{collection_id}", status_code=204)
def delete_collection(collection_id: str, images: ImageStore = Depends(get_images)) -> Response:
    try:
        images.delete(collection_id)
    except CollectionNotFound:
        raise HTTPException(status_code=404, detail="Image collection not found or expired")
    return Response(status_code=204)


@router.post("/{collection_id}/items", response_model=CollectionOut)
async def add_images(
    collection_id: str,
    files: Annotated[list[UploadFile], File(description="JPEG, PNG, WebP or TIFF images")],
    last_modified: LastModified = None,
    images: ImageStore = Depends(get_images),
) -> CollectionOut:
    await run_in_threadpool(_load, images, collection_id)
    return await _add_files(images, collection_id, files, last_modified)


@router.put("/{collection_id}/bundle", response_model=CollectionOut)
async def put_bundle(collection_id: str, body: DatasetInfoIO, images: ImageStore = Depends(get_images)) -> CollectionOut:
    """The bundle defaults every image inherits where its own field is empty."""

    def fn(coll: ImageCollection):
        coll.bundle = body.to_info()
        return CollectionOut.build(coll)

    return await _change(images, collection_id, fn)


# -- one image ------------------------------------------------------------------------


@router.delete("/{collection_id}/items/{image_id}", response_model=CollectionOut)
async def delete_image(collection_id: str, image_id: str, images: ImageStore = Depends(get_images)) -> CollectionOut:
    def fn(coll: ImageCollection):
        _item(coll, image_id)
        images.remove(coll, image_id)
        return CollectionOut.build(coll)

    return await _change(images, collection_id, fn)


@router.get("/{collection_id}/items/{image_id}/{kind}.jpg", response_class=FileResponse)
def get_picture(collection_id: str, image_id: str, kind: str, images: ImageStore = Depends(get_images)) -> FileResponse:
    """``thumb`` or ``preview``: the stored JPEG."""
    try:
        path = images.picture(collection_id, image_id, kind)
    except CollectionNotFound:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.put("/{collection_id}/items/{image_id}/info", response_model=ImageOut)
async def put_image_info(
    collection_id: str, image_id: str, body: DatasetInfoIO, images: ImageStore = Depends(get_images)
) -> ImageOut:
    """The image's own fields; leave one empty to inherit it from the bundle."""

    def fn(coll: ImageCollection):
        item = _item(coll, image_id)
        item.info = body.to_info()
        return ImageOut.build(coll, item)

    return await _change(images, collection_id, fn)


@router.put("/{collection_id}/items/{image_id}/suggestion", response_model=ImageOut)
async def put_suggestion(
    collection_id: str, image_id: str, body: SuggestionIO | None = None, images: ImageStore = Depends(get_images)
) -> ImageOut:
    """What is left of the AI suggestion after the user accepted or rejected parts of it
    (no body, or an empty one, clears it)."""

    def fn(coll: ImageCollection):
        item = _item(coll, image_id)
        sug = Suggestion(**body.model_dump()) if body else None
        item.suggestion = None if sug is None or sug.empty else sug
        return ImageOut.build(coll, item)

    return await _change(images, collection_id, fn)


@router.post("/{collection_id}/items/{image_id}/describe", response_model=ImageOut)
async def describe_image(collection_id: str, image_id: str, images: ImageStore = Depends(get_images)) -> ImageOut:
    """Ask the vision model for a title, description and keywords. The answer is stored
    as a suggestion; nothing in the image's description changes until the user accepts it."""
    if not settings.n8n_bearer_key:
        raise HTTPException(status_code=503, detail="AI description is not configured (set DDI_N8N_BEARER_KEY)")

    def start(coll: ImageCollection):
        item = _item(coll, image_id)
        item.ai_status, item.ai_error = "running", ""
        return item.filename

    filename = await _change(images, collection_id, start)
    try:
        preview = await run_in_threadpool(lambda: images.picture(collection_id, image_id, "preview").read_bytes())
        async with admission.enrichments.slot():
            suggestion, error = await ai.describe(preview, filename), ""
    except (EnrichError, NotConfigured, CollectionNotFound) as exc:
        suggestion, error = None, str(exc) or "the image could not be described"

    def finish(coll: ImageCollection):
        item = _item(coll, image_id)
        if suggestion is None:
            item.ai_status, item.ai_error = "failed", error
        else:
            item.ai_status, item.ai_error, item.suggestion = "done", "", suggestion
        return ImageOut.build(coll, item)

    return await _change(images, collection_id, finish)


# -- output ---------------------------------------------------------------------------


@router.get("/{collection_id}/items/{image_id}/cdif")
def get_image_cdif(collection_id: str, image_id: str, images: ImageStore = Depends(get_images)) -> Response:
    coll = _load(images, collection_id)
    item = _item(coll, image_id)
    name = cdif_filename(item, set())
    return Response(
        dumps(image_cdif(coll, item)),
        media_type="application/ld+json",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@router.get("/{collection_id}/cdif.zip")
def get_collection_zip(collection_id: str, images: ImageStore = Depends(get_images)) -> Response:
    """One CDIF file per image, ``<image name>.cdif.jsonld``."""
    coll = _load(images, collection_id)
    buf, taken = io.BytesIO(), set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in coll.images:
            zf.writestr(cdif_filename(item, taken), dumps(image_cdif(coll, item)))
    return Response(
        buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="images_CDIF.zip"'},
    )


@router.post("/{collection_id}/check", response_model=list[ImageCheckOut])
async def check_collection(collection_id: str, images: ImageStore = Depends(get_images)) -> list[ImageCheckOut]:
    """Each image's CDIF against the CDIF Discovery shapes (the profile it declares), plus
    the required fields left empty."""
    coll = await run_in_threadpool(_load, images, collection_id)
    out = []
    for item in coll.images:
        graph = await run_in_threadpool(lambda i=item: qlever.cdif_graph(image_cdif(coll, i)))
        async with admission.validations.slot():
            shacl = await run_in_threadpool(qlever.shacl_check, graph, shapes=qlever.DISCOVERY_SHAPES)
        info = effective_info(coll.bundle, item)
        info.title = item.info.title  # the file name stands in for a missing title
        missing = qlever.missing_required(info, item.filename)
        out.append(ImageCheckOut(id=item.uid, filename=item.filename, shacl=ShaclOut(**shacl, missing_required=missing)))
    return out
