"""Save CDIF to a QLever SPARQL store, and read it back.

Design: QLever-deployment/grilling-summary.md (Q2-Q9). In short:

* Every saved document is one named graph, ``urn:uuid:<doc_uuid>``, replaced as a whole
  by each save (Graph Store HTTP ``PUT ?graph=``). The UUID is minted at import and kept
  in the workspace, so a re-save replaces the same graph.
* The dataset IRI is the editor's record IRI (``DatasetInfo.record_id``), by default
  ``urn:uuid:<doc_uuid>``. Every other node already has a ``urn:uuid:`` IRI derived from
  the document UUID (``cdi/ids.py``), so nodes of two documents never share an IRI.
* One catalog entry per document lives in the graph ``urn:cdi-studio:catalog``; Import
  lists documents from it.
* QLever refuses JSON-LD (415), so the CDIF goes in as N-Triples. Not Turtle: rdflib
  writes an ``xsd:double`` such as ``7.6429`` in Turtle's short form, which reads back
  as ``xsd:decimal``.
* QLever keeps numbers in its own numeric types: it returns every integer as ``xsd:int``
  and every floating-point number as ``xsd:decimal``. CDIF from the editor carries only
  JSON-LD's native ``xsd:integer`` and ``xsd:double``, so :func:`restore_numeric_types`
  maps them back on import. QLever stores a double in full but writes it with only 12-13
  significant digits (1.7653369903564453 is read back as 1.765336990356), so statistics
  read back are rounded there.

Only updates need the access token. Reads are open to anyone who reaches the port.
"""

from __future__ import annotations

import json
import multiprocessing
import re
import threading
import uuid as uuidlib
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anyio
import httpx
from rdflib import RDF, XSD, Graph, Literal, Namespace, URIRef

from .cdif.ddicdi_jsonld_to_cdif import CDI_CTX, NIL_MISSING, UNKNOWN_DATE
from .config import settings
from .models import DatasetInfo

CATALOG = URIRef("urn:cdi-studio:catalog")
# The record IRI imports wrote before documents had UUIDs (``urn:ddi-cdi:<file stem>``);
# a save replaces it.
PLACEHOLDER_RECORD_PREFIX = "urn:ddi-cdi:"
DCAT = Namespace("http://www.w3.org/ns/dcat#")
DCT = Namespace("http://purl.org/dc/terms/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
VOID = Namespace("http://rdfs.org/ns/void#")

# The context of the converter's output, for JSON-LD read back from the store.
CDIF_CONTEXT: dict[str, str] = dict(CDI_CTX, spdx="http://spdx.org/rdf/terms#", xsd=str(XSD))

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# An absolute IRI: a scheme, then no whitespace or characters N-Triples cannot hold in <>.
_IRI_RE = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*:[^\s<>"{}|\\^`]+$')


class QleverError(Exception):
    """The store is not configured, not reachable, or refused a request."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


# -- identity --------------------------------------------------------------------------


def new_uuid() -> str:
    return str(uuidlib.uuid4())


def is_uuid(value: str) -> bool:
    return bool(_UUID_RE.match(value))


def graph_iri(doc_uuid: str) -> str:
    return f"urn:uuid:{doc_uuid}"


def entry_iri(doc_uuid: str) -> URIRef:
    return URIRef(f"urn:cdi-studio:entry:{doc_uuid}")


def is_absolute_iri(value: str) -> bool:
    return bool(_IRI_RE.match(value))


# -- CDIF -> RDF -----------------------------------------------------------------------


def cdif_graph(cdif: dict) -> Graph:
    """The CDIF JSON-LD as an RDF graph. Its context is inline: nothing is fetched."""
    graph = Graph()
    graph.parse(data=json.dumps(cdif), format="json-ld")
    return graph


def restore_numeric_types(graph: Graph) -> Graph:
    """QLever's ``xsd:int`` / ``xsd:decimal`` back to the ``xsd:integer`` / ``xsd:double``
    the editor's CDIF uses (see the module notes)."""
    out = Graph()
    for s, p, o in graph:
        if isinstance(o, Literal) and o.datatype == XSD.int:
            o = Literal(str(o), datatype=XSD.integer)
        elif isinstance(o, Literal) and o.datatype == XSD.decimal:
            o = Literal(str(o), datatype=XSD.double)
        out.add((s, p, o))
    return out


def to_jsonld(graph: Graph) -> dict:
    """The graph as compact JSON-LD with the CDIF context (flat ``@graph``: rdflib does
    no framing, so the nesting of the original document is not rebuilt)."""
    return json.loads(graph.serialize(format="json-ld", context=CDIF_CONTEXT, auto_compact=True))


def to_turtle(graph: Graph) -> str:
    for prefix, ns in CDIF_CONTEXT.items():
        graph.bind(prefix, ns, override=True, replace=True)
    return graph.serialize(format="turtle")


# -- SHACL (warn, don't block) ---------------------------------------------------------


# Vendored with the app (Apache-2.0, see shapes/README.md), so the image has them too.
VENDORED_SHAPES = Path(__file__).resolve().parent / "cdif" / "shapes" / "CDIF-Complete-Shapes.ttl"


def _shapes_file() -> Path | None:
    shapes = Path(settings.cdif_shacl_shapes) if settings.cdif_shacl_shapes else VENDORED_SHAPES
    return shapes if shapes.is_file() else None


def missing_required(info: DatasetInfo, datafile: str) -> list[str]:
    """The required fields of the Dataset tab's CDIF checklist that are empty, and what
    the converter writes in their place. SHACL cannot see these: the stand-in is a value
    (the file name as title, a "missing" licence, 1900-01-01), so its rules are satisfied."""
    problems = []
    if not info.title.strip():
        problems.append(f"Title is missing (the file name {Path(datafile).stem!r} is used instead)")
    if not info.license.strip():
        problems.append(f"Licence is missing (written as the placeholder {NIL_MISSING})")
    if not info.date_modified:
        problems.append(f"Date modified is missing (written as the placeholder {UNKNOWN_DATE})")
    return problems


def shacl_check(graph: Graph, max_messages: int = 50) -> dict:
    """Validate against the CDIF SHACL shapes, when they and pyshacl are available.

    The result never stops a save: ``checked`` says whether validation ran at all. A
    graph over ``settings.shacl_max_triples`` is not checked, and validation runs in a
    child process that is stopped after ``settings.shacl_timeout`` seconds (security
    #10): pyshacl cannot be interrupted, and a thread would hold the GIL meanwhile.
    """
    shapes = _shapes_file()
    if shapes is None:
        return _not_checked(f"CDIF SHACL shapes not found ({settings.cdif_shacl_shapes or VENDORED_SHAPES.name})")
    try:
        import pyshacl  # noqa: F401
    except ImportError:
        return _not_checked("pyshacl is not installed")
    limit = settings.shacl_max_triples
    if limit > 0 and len(graph) > limit:
        return _not_checked(f"the document has {len(graph):,} triples; documents over {limit:,} are not checked")
    if settings.shacl_timeout <= 0:
        return _validate(graph, shapes, max_messages)
    data = graph.serialize(format="nt", encoding="utf-8")
    return _validate_in_child(data, shapes, max_messages, settings.shacl_timeout)


def _not_checked(reason: str) -> dict:
    return {"checked": False, "reason": reason, "violations": [], "warnings": 0}


def _validate(graph: Graph, shapes: Path, max_messages: int) -> dict:
    from pyshacl import validate

    sh = Namespace("http://www.w3.org/ns/shacl#")
    _, report, _ = validate(graph, shacl_graph=str(shapes), inference="none", advanced=True, allow_warnings=True)
    violations: list[str] = []
    warnings: list[str] = []
    for result in report.subjects(sh.resultSeverity, None):
        severity = report.value(result, sh.resultSeverity)
        message = str(report.value(result, sh.resultMessage) or "")
        if severity == sh.Violation:
            focus = report.value(result, sh.focusNode)
            violations.append(f"{message} ({focus})" if focus is not None else message)
        elif severity == sh.Warning:
            warnings.append(message)  # mostly "X is recommended": the same for every node
    return {"checked": True, "shapes": shapes.name,
            "violations": sorted(set(violations))[:max_messages], "violation_count": len(violations),
            "warnings": len(warnings), "warning_messages": sorted(set(warnings))[:max_messages]}


def _validate_nt(data: bytes, shapes: str, max_messages: int) -> dict:
    """Worker process entry point: validate the N-Triples ``data``."""
    graph = Graph()
    graph.parse(data=data, format="nt")
    return _validate(graph, Path(shapes), max_messages)


# Worker processes for SHACL validation, kept warm between checks (starting one costs
# ~2 s of imports). A validation over its deadline kills the pool; the next starts anew.
_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()


def _executor() -> ProcessPoolExecutor:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ProcessPoolExecutor(
                max_workers=max(1, settings.max_concurrent_validations),
                mp_context=multiprocessing.get_context("spawn"),  # never fork a process with threads
            )
        return _pool


def _kill_pool(pool: ProcessPoolExecutor) -> None:
    global _pool
    with _pool_lock:
        if _pool is pool:
            _pool = None
    for proc in list(getattr(pool, "_processes", {}).values()):
        proc.kill()
    pool.shutdown(wait=False, cancel_futures=True)


def _validate_in_child(data: bytes, shapes: Path, max_messages: int, timeout: float) -> dict:
    pool = _executor()
    try:
        future = pool.submit(_validate_nt, data, str(shapes), max_messages)
        return future.result(timeout=timeout)
    except FuturesTimeout:
        _kill_pool(pool)
        return _not_checked(f"validation took longer than {timeout:g}s and was stopped")
    except BrokenProcessPool:
        _kill_pool(pool)
        return _not_checked("validation stopped unexpectedly")
    except Exception as exc:
        return _not_checked(f"validation failed: {exc.__class__.__name__}: {str(exc)[:300]}")


# -- the store -------------------------------------------------------------------------


def configured() -> bool:
    return bool(settings.qlever_url)


def _url() -> str:
    if not settings.qlever_url:
        raise QleverError("QLever is not configured (DDI_QLEVER_URL)", status_code=503)
    return settings.qlever_url.rstrip("/") + "/"


def _auth() -> dict[str, str]:
    if not settings.qlever_access_token:
        raise QleverError("No QLever access token configured (DDI_QLEVER_ACCESS_TOKEN)", status_code=503)
    return {"Authorization": f"Bearer {settings.qlever_access_token}"}


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.qlever_timeout)


def _check(response: httpx.Response, what: str) -> httpx.Response:
    if response.status_code >= 400:
        detail = response.text[:500].strip()
        if response.status_code in (401, 403):
            raise QleverError(f"QLever refused the {what}: check DDI_QLEVER_ACCESS_TOKEN ({response.status_code})")
        raise QleverError(f"QLever {what} failed ({response.status_code}): {detail}")
    return response


async def _send(method: str, what: str, **kwargs) -> httpx.Response:
    url = _url()
    try:
        async with _client() as client:
            response = await client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise QleverError(f"QLever is not reachable at {url}: {exc.__class__.__name__}") from exc
    return _check(response, what)


async def put_graph(graph_name: str, graph: Graph) -> None:
    """Replace the named graph with ``graph`` (Graph Store HTTP PUT)."""
    # Serialising a large graph is CPU work: off the event loop (GitLab #10).
    body = await anyio.to_thread.run_sync(lambda: graph.serialize(format="nt", encoding="utf-8"))
    await _send("PUT", "save", params={"graph": graph_name}, content=body,
                headers={**_auth(), "Content-Type": "application/n-triples"})


async def update(sparql: str) -> None:
    await _send("POST", "update", data={"update": sparql}, headers=_auth())


async def select(sparql: str) -> list[dict[str, Any]]:
    response = await _send("POST", "query", data={"query": sparql},
                           headers={"Accept": "application/sparql-results+json"})
    return response.json()["results"]["bindings"]


async def construct_graph(graph_name: str) -> Graph:
    """Every triple of one named graph, as stored (numeric types as QLever returns them).

    At most ``settings.qlever_max_document_bytes`` of N-Triples are read (413 above it),
    and they are parsed off the event loop (GitLab #18).
    """
    query = f"CONSTRUCT {{ ?s ?p ?o }} WHERE {{ GRAPH <{graph_name}> {{ ?s ?p ?o }} }}"
    data = await _read_capped(
        "query", settings.qlever_max_document_bytes,
        data={"query": query}, headers={"Accept": "application/n-triples"},
    )

    def parse() -> Graph:
        graph = Graph()
        graph.parse(data=data, format="nt")
        return graph

    return await anyio.to_thread.run_sync(parse)


async def _read_capped(what: str, max_bytes: int, **kwargs) -> bytes:
    """A POST to QLever whose response body is read up to ``max_bytes`` (0 = no cap)."""
    url = _url()
    try:
        async with _client() as client:
            async with client.stream("POST", url, **kwargs) as response:
                if response.status_code >= 400:
                    await response.aread()
                    _check(response, what)
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if max_bytes > 0 and size > max_bytes:
                        raise QleverError(
                            f"The saved document is larger than {max_bytes} bytes and cannot be read back here",
                            status_code=413,
                        )
                    chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise QleverError(f"QLever is not reachable at {url}: {exc.__class__.__name__}") from exc
    return b"".join(chunks)


# -- catalog ---------------------------------------------------------------------------


@dataclass
class CatalogEntry:
    uuid: str
    title: str
    dataset_iri: str
    source_file: str
    triples: int
    saved_at: str
    saved_by: str = ""

    @property
    def graph(self) -> str:
        return graph_iri(self.uuid)


def _entry_graph(entry: CatalogEntry) -> Graph:
    g = Graph()
    e = entry_iri(entry.uuid)
    g.add((CATALOG, DCAT.record, e))
    g.add((e, RDF.type, DCAT.CatalogRecord))
    g.add((e, DCT.identifier, Literal(entry.uuid)))
    g.add((e, DCT.title, Literal(entry.title)))
    g.add((e, FOAF.primaryTopic, URIRef(entry.dataset_iri)))
    g.add((e, DCT.source, Literal(entry.source_file)))
    g.add((e, DCT.modified, Literal(entry.saved_at, datatype=XSD.dateTime)))
    g.add((e, VOID.triples, Literal(entry.triples)))
    if entry.saved_by:
        g.add((e, DCT.creator, Literal(entry.saved_by)))
    return g


async def write_catalog_entry(entry: CatalogEntry) -> None:
    """Replace the catalog entry of one document."""
    e = entry_iri(entry.uuid)
    triples = _entry_graph(entry).serialize(format="nt")
    await update(
        f"DELETE WHERE {{ GRAPH <{CATALOG}> {{ <{e}> ?p ?o }} }} ;\n"
        f"INSERT DATA {{ GRAPH <{CATALOG}> {{\n{triples}}} }}"
    )


async def list_catalog() -> list[dict[str, Any]]:
    rows = await select(
        f"""PREFIX dct: <{DCT}> PREFIX dcat: <{DCAT}> PREFIX foaf: <{FOAF}> PREFIX void: <{VOID}>
SELECT ?uuid ?title ?dataset ?source ?modified ?creator ?triples WHERE {{
  GRAPH <{CATALOG}> {{
    <{CATALOG}> dcat:record ?e . ?e dct:identifier ?uuid .
    OPTIONAL {{ ?e dct:title ?title }} OPTIONAL {{ ?e foaf:primaryTopic ?dataset }}
    OPTIONAL {{ ?e dct:source ?source }} OPTIONAL {{ ?e dct:modified ?modified }}
    OPTIONAL {{ ?e dct:creator ?creator }} OPTIONAL {{ ?e void:triples ?triples }}
  }}
}} ORDER BY DESC(?modified)"""
    )

    def val(row: dict, key: str) -> str | None:
        return row[key]["value"] if key in row else None

    def num(row: dict, key: str) -> int | None:
        v = val(row, key)
        return int(float(v)) if v is not None else None

    return [
        {
            "uuid": val(r, "uuid"),
            "graph": graph_iri(val(r, "uuid") or ""),
            "title": val(r, "title") or "",
            "dataset_iri": val(r, "dataset"),
            "source_file": val(r, "source"),
            "saved_at": val(r, "modified"),
            "saved_by": val(r, "creator"),
            "triples": num(r, "triples"),
        }
        for r in rows
    ]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
