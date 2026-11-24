"""CDIF for one image: a schema:Dataset with schema:additionalType schema:ImageObject.

The root and its discovery terms come from the same converter as a tabular document
(``convert_document`` with an empty DDI-CDI model), so the two read alike. The image
itself is the distribution: a schema:DataDownload with the image's media type, size and
checksum, and its contentUrl when the user gave one. There are no variables, so the
record conforms to CDIF core and discovery only.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..cdif import convert_document, info_header
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
