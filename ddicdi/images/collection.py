"""An image collection: shared bundle defaults and one description per image.

Each image becomes its own CDIF Dataset. The bundle carries what images usually share
(licence, creators, publisher, ...); an image inherits every bundle field it leaves
empty. Fields that name one image (title, description, identifiers, URLs) are never
inherited, and keywords are the image's own followed by the bundle's.

A collection lives in the same work directory as tabular uploads, as
``<id>/collection.json`` plus a JPEG preview and thumbnail per image, and expires with
them (``UploadStore.cleanup_expired``). It has no meta.json, so the tabular endpoints
see no upload under its id.
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from ..config import settings
from ..editing import work_dir_usage
from ..models import DatasetInfo
from .media import Processed

COLLECTION_FILE = "collection.json"

# Fields of DatasetInfo that describe one image only, so an image never inherits them.
OWN_FIELDS = frozenset({"title", "description", "identifier", "url", "content_url", "record_id", "keywords"})

# AI description of one image: not asked yet, asked, answered, failed.
AI_STATES = ("pending", "running", "done", "failed")


class CollectionNotFound(KeyError):
    pass


class CollectionFull(ValueError):
    """More images than ``settings.max_images``."""


class StorageFull(OSError):
    pass


@dataclass
class Suggestion:
    """What the model proposed and the user has not yet accepted or rejected. A field the
    user has dealt with is cleared (empty string / list)."""

    title: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.title or self.description or self.keywords)


@dataclass
class ImageItem:
    uid: str
    filename: str
    mime: str
    width: int
    height: int
    size: int
    md5: str
    info: DatasetInfo = field(default_factory=DatasetInfo)
    ai_status: str = "pending"
    ai_error: str = ""
    suggestion: Suggestion | None = None

    @property
    def record_iri(self) -> str:
        return self.info.record_id.strip() or f"urn:uuid:{self.uid}"

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ImageItem":
        known = {f.name for f in fields(cls)}
        sug = d.get("suggestion")
        return cls(
            **{
                **{k: v for k, v in d.items() if k in known},
                "info": DatasetInfo.from_dict(d.get("info") or {}),
                "suggestion": Suggestion(**sug) if sug else None,
            }
        )


@dataclass
class ImageCollection:
    uid: str
    bundle: DatasetInfo = field(default_factory=DatasetInfo)
    images: list[ImageItem] = field(default_factory=list)

    def image(self, image_id: str) -> ImageItem:
        for item in self.images:
            if item.uid == image_id:
                return item
        raise CollectionNotFound(image_id)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ImageCollection":
        return cls(
            uid=d["uid"],
            bundle=DatasetInfo.from_dict(d.get("bundle") or {}),
            images=[ImageItem.from_dict(i) for i in d.get("images", [])],
        )


def effective_info(bundle: DatasetInfo, item: ImageItem) -> DatasetInfo:
    """The description written for ``item``: its own fields, bundle fields where it has
    none (except ``OWN_FIELDS``), its file name as the title when it has none."""
    own = item.info
    values: dict[str, Any] = {}
    for f in fields(DatasetInfo):
        mine = getattr(own, f.name)
        if f.name in OWN_FIELDS or mine:
            values[f.name] = mine
        else:
            values[f.name] = getattr(bundle, f.name)
    seen = {k.strip().lower() for k in own.keywords}
    values["keywords"] = [k for k in own.keywords if k.strip()] + [
        k for k in bundle.keywords if k.strip() and k.strip().lower() not in seen
    ]
    values["title"] = own.title.strip() or Path(item.filename).stem
    values["record_id"] = item.record_iri
    return DatasetInfo(**values)


class ImageStore:
    """Image collections under ``root`` (the tabular uploads' work directory)."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, collection_id: str) -> Path:
        if not collection_id.isalnum():
            raise CollectionNotFound(collection_id)
        return self.root / collection_id

    def _file(self, collection_id: str) -> Path:
        path = self._dir(collection_id) / COLLECTION_FILE
        if not path.exists():
            raise CollectionNotFound(collection_id)
        return path

    def create(self) -> ImageCollection:
        coll = ImageCollection(uid=uuid.uuid4().hex)
        self._dir(coll.uid).mkdir(parents=True)
        self.save(coll)
        return coll

    def load(self, collection_id: str) -> ImageCollection:
        path = self._file(collection_id)
        try:
            os.utime(path.parent)  # the TTL counts from the last use
        except OSError:
            pass
        return ImageCollection.from_dict(json.loads(path.read_text()))

    def save(self, coll: ImageCollection) -> None:
        d = self._dir(coll.uid)
        tmp = d / (COLLECTION_FILE + ".tmp")
        tmp.write_text(json.dumps(coll.to_dict(), ensure_ascii=False))
        tmp.replace(d / COLLECTION_FILE)

    def delete(self, collection_id: str) -> None:
        self._file(collection_id)
        shutil.rmtree(self._dir(collection_id), ignore_errors=True)

    def picture(self, collection_id: str, image_id: str, kind: str) -> Path:
        """The stored preview or thumbnail of an image of the collection."""
        if kind not in ("preview", "thumb") or not image_id.isalnum():
            raise CollectionNotFound(image_id)
        path = self._dir(collection_id) / f"{image_id}.{kind}.jpg"
        if not path.exists():
            raise CollectionNotFound(image_id)
        return path

    def add(self, coll: ImageCollection, filename: str, processed: Processed, modified: str = "") -> ImageItem:
        """Store the pictures of one more image; the caller saves the collection.

        Its dates start from the import: published is the day the photo was taken
        (EXIF) or else the file's last-modified day ``modified``; modified is that day
        or else the day taken. Both stay editable."""
        if settings.max_images > 0 and len(coll.images) >= settings.max_images:
            raise CollectionFull(f"a collection holds at most {settings.max_images} images")
        quota = settings.work_dir_max_bytes
        extra = len(processed.preview) + len(processed.thumb)
        if quota > 0 and work_dir_usage(self.root) + extra > quota:
            raise StorageFull(f"the server's upload storage is full (limit {quota} bytes); try again later")
        item = ImageItem(
            uid=uuid.uuid4().hex,
            filename=Path(filename).name or "image",
            mime=processed.mime,
            width=processed.width,
            height=processed.height,
            size=processed.size,
            md5=processed.md5,
        )
        item.info.date_published = processed.taken or modified
        item.info.date_modified = modified or processed.taken
        d = self._dir(coll.uid)
        (d / f"{item.uid}.preview.jpg").write_bytes(processed.preview)
        (d / f"{item.uid}.thumb.jpg").write_bytes(processed.thumb)
        coll.images.append(item)
        return item

    @staticmethod
    def default_bundle_dates(coll: ImageCollection) -> None:
        """Empty bundle dates from the images: the earliest published, the latest modified."""
        published = sorted(i.info.date_published for i in coll.images if i.info.date_published)
        modified = sorted(i.info.date_modified for i in coll.images if i.info.date_modified)
        if not coll.bundle.date_published and published:
            coll.bundle.date_published = published[0]
        if not coll.bundle.date_modified and modified:
            coll.bundle.date_modified = modified[-1]

    def remove(self, coll: ImageCollection, image_id: str) -> None:
        item = coll.image(image_id)
        coll.images.remove(item)
        d = self._dir(coll.uid)
        for kind in ("preview", "thumb"):
            (d / f"{item.uid}.{kind}.jpg").unlink(missing_ok=True)
