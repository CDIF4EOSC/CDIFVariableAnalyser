"""CDIF for one image: a schema:Dataset with schema:additionalType schema:ImageObject.

The root and its discovery terms come from the same converter as a tabular document
(``convert_document`` with an empty DDI-CDI model), so the two read alike. The image
itself is the distribution: a schema:DataDownload with the image's media type, size and
checksum, and its contentUrl when the user gave one. There are no variables, so the
record conforms to CDIF core and discovery only.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from rdflib import Graph

from ..cdif import convert_document, info_header
from ..cdif.reverse import SCHEMA, SPDX, NotADocument, _dataset_node, _info, _int, _str
from .collection import ImageCollection, ImageItem, effective_info

CONFORMS_TO = [
    {"@id": "https://w3id.org/cdif/core/1.1"},
    {"@id": "https://w3id.org/cdif/discovery/1.1"},
]

RECORD_NOTE = "Metadata record for an image, written by DDI-CDI Studio in the CDIF discovery profile."


def _after(doc: dict, anchor: str, key: str, value) -> dict:
    """``doc`` with ``key`` set and placed right after ``anchor`` (at the end without it)."""
    out: dict = {}
    for k, v in doc.items():
        if k == key:
            continue
        out[k] = v
        if k == anchor:
            out[key] = value
    out.setdefault(key, value)
    return out


def image_cdif(coll: ImageCollection, item: ImageItem) -> dict:
    info = effective_info(coll.bundle, item)
    header = info_header(info, item.size, item.md5)
    doc = convert_document(header, Path(item.filename).stem, explicit_id=item.record_iri)
    # Right after @type, so a reader sees at once that the record is about an image
    # (key order means nothing in JSON-LD; it is only for people reading the file).
    doc = _after(doc, "@type", "schema:additionalType", [{"@id": "schema:ImageObject"}])
    dist = doc["schema:distribution"][0]
    dist["schema:name"] = item.filename
    dist["schema:encodingFormat"] = [item.mime]
    record = doc["schema:subjectOf"]
    record["schema:description"] = RECORD_NOTE
    record["dcterms:conformsTo"] = [dict(c) for c in CONFORMS_TO]
    return doc


def cdif_filename(item: ImageItem, taken: set[str]) -> str:
    """``<image stem>.cdif.jsonld``, numbered when two images share a stem."""
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in Path(item.filename).stem) or "image"
    name, n = f"{stem}.cdif.jsonld", 2
    while name in taken:
        name, n = f"{stem}-{n}.cdif.jsonld", n + 1
    taken.add(name)
    return name


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, ensure_ascii=False)


# -- read back (Open from QLever) ------------------------------------------------------


def is_image_graph(g: Graph) -> bool:
    """Whether a saved CDIF document is an image record (additionalType ImageObject)."""
    return any(True for _ in g.subjects(SCHEMA.additionalType, SCHEMA.ImageObject))


def image_from_graph(g: Graph, doc_uuid: str) -> ImageItem:
    """One saved image record -> an image without its picture, for editing.

    Its id is the document UUID, so the next save replaces the same graph. Every field
    comes back as the image's own (CDIF holds the values with the bundle's merged in),
    and the pixel size is unknown (CDIF does not carry it). The record IRI is kept;
    a title equal to the file name (the stand-in for a missing title) comes back empty.
    """
    if not is_image_graph(g):
        raise NotADocument("Not an image record (no schema:additionalType schema:ImageObject)")
    ds = _dataset_node(g)
    dist = g.value(ds, SCHEMA.distribution)
    info = _info(g, ds, dist)
    filename = (_str(g, dist, SCHEMA.name) if dist is not None else "") or "image"
    if info.title == Path(filename).stem:
        info.title = ""  # the file name stood in for a missing title: empty again
    checksum = g.value(dist, SPDX.checksum) if dist is not None else None
    return ImageItem(
        uid=uuid.UUID(doc_uuid).hex,
        filename=filename,
        mime=(_str(g, dist, SCHEMA.encodingFormat) if dist is not None else "") or "image/jpeg",
        width=0,
        height=0,
        size=(_int(g, dist, SCHEMA.contentSize) if dist is not None else None) or 0,
        md5=_str(g, checksum, SPDX.checksumValue) if checksum is not None else "",
        info=info,
        ai_status="done",
        has_picture=False,
    )
