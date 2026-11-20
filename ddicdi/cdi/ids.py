"""One identifier policy for every element: ``urn:uuid:<uuid>``.

The generator and the CDIF converter build readable symbolic ids (``#instanceVariable-age``,
``#code-age-1``) and refer to nodes by them. :func:`assign_ids` turns a finished document
into one where every node, the nested ones included, has a ``urn:uuid:`` IRI:

* Two UUIDs are stored: the document's (``DatasetMeta.doc_uuid``, minted at import) and
  each variable's (``Variable.uid``, minted when the variable is created and kept when it
  is renamed).
* A variable's IRI is ``urn:uuid:<its uid>``. Every other UUID is derived, never stored: ``uuid5(document UUID, key)``, where the key
  is the symbolic id with the variable name replaced by the variable's UUID. The same
  element therefore gets the same IRI on every save, in the DDI-CDI and the CDIF output
  alike, and keeps it when its variable is renamed.
* A node without an id (a name, a label, a statistic's value, a creator) gets
  ``uuid5(document UUID, "<parent key>/<property>/<index>")``.

Not touched: the ``@context``, external IRIs (``http...``, ``xsd:double``), the dataset
IRI of a CDIF document, and the cells of an RDF ``@list`` (JSON-LD cannot name them).
"""

from __future__ import annotations

import uuid
from typing import Any

from ..models import DatasetMeta

# Symbolic id kinds that carry a variable name, as ``<kind>-<variable>[-<rest>]``.
_VARIABLE_KINDS = frozenset({
    "textMapping", "locatorMapping", "physicalMappingPosition", "instanceVariable",
    "measureComponent", "identifierComponent", "attributeComponent", "primaryKeyComponent",
    "substantiveValueDomain", "sentinelValueDomain", "substantiveValueAndConceptDescription",
    "sentinelValueAndConceptDescription", "substantiveCodeList", "sentinelCodeList", "concept",
    "code", "codePosition", "category", "notation", "statisticsCollection", "statistics",
    "categoryStatistics",
})
# ... and these as ``<kind>-<row>-<variable>``.
_ROW_KINDS = frozenset({"dataPoint", "dataPointPosition", "instanceValue"})

# Keys whose strings are text, never references: a label that happens to read like an id
# must stay text.
_TEXT_KEYS = frozenset({"content", "name", "entryValue", "locator", "physicalFileName", "value",
                        "schema:name", "schema:description", "schema:value"})

_JSONLD_KEYWORDS_WITHOUT_NODES = frozenset({"@context", "@type", "@value", "@language", "@direction"})


def is_value_object(obj: dict) -> bool:
    return "@value" in obj


class IdMap:
    """Maps the symbolic ids of one document to ``urn:uuid:`` IRIs."""

    def __init__(self, meta: DatasetMeta, base_iri: str | None = None, readable: bool = False):
        # ``readable`` keeps the symbolic ids (DDI_READABLE_IDS): nothing is renamed, but
        # the variable of each element is still recorded.
        self.readable = readable
        self.namespace = uuid.UUID(meta.doc_uuid)
        self.var_keys = {v.name: v.uid for v in meta.variables}
        # Only the first ``_name_span`` characters of a fragment's rest can hold a
        # variable name, so finding one costs the same however long a code is (#8).
        self._name_span = max((len(n) for n in self.var_keys), default=0)
        self._keys: dict[str, tuple[str, str | None]] = {}
        # A CDIF document anchors some ids on its dataset IRI (``<iri>#cdif-catalog-record``).
        self.base = base_iri + "#" if base_iri else None
        self._cache: dict[str, str] = {}
        # variable name -> the IRIs of the elements made for it (for the editor preview)
        self.by_variable: dict[str, set[str]] = {}

    def symbolic(self, value: str) -> str | None:
        """The fragment of a symbolic id, or None when ``value`` is not one."""
        if value.startswith("#"):
            return value[1:]
        if self.base and value.startswith(self.base):
            return value[len(self.base):]
        return None

    def _stable_key(self, fragment: str) -> tuple[str, str | None]:
        """The fragment with its variable name replaced by the variable UUID, and the name."""
        hit = self._keys.get(fragment)
        if hit is None:
            hit = self._keys[fragment] = self._find_key(fragment)
        return hit

    def _find_key(self, fragment: str) -> tuple[str, str | None]:
        kind, sep, rest = fragment.partition("-")
        if not sep:
            return fragment, None
        prefix = kind + "-"
        if kind in _ROW_KINDS:
            row, sep, rest = rest.partition("-")
            if not sep:
                return fragment, None
            prefix += row + "-"
        elif kind not in _VARIABLE_KINDS:
            return fragment, None
        # The longest variable name that starts ``rest`` and is followed by its end or "-".
        # No name is longer than ``_name_span``, so only the cuts within that span are
        # tried: the work is bounded by the longest name, not by the code after it.
        span = self._name_span
        cuts = [i for i, c in enumerate(rest[: span + 1]) if c == "-"]
        if len(rest) <= span:
            cuts.append(len(rest))
        for cut in reversed(cuts):
            name = rest[:cut]
            if name in self.var_keys:
                return prefix + self.var_keys[name] + rest[cut:], name
        return fragment, None

    def iri(self, fragment: str, original: str | None = None) -> str:
        hit = self._cache.get(fragment)
        if hit is None:
            key, name = self._stable_key(fragment)
            if self.readable:
                hit = original or "#" + fragment
            elif name is not None and key == "instanceVariable-" + self.var_keys[name]:
                # A variable is named by its own stored UUID, so reading a document
                # back (Open from QLever) recovers the variable's identity.
                hit = f"urn:uuid:{self.var_keys[name]}"
            else:
                hit = self.derive(key)
            self._cache[fragment] = hit
            if name is not None:
                self.by_variable.setdefault(name, set()).add(hit)
        return hit

    def derive(self, key: str) -> str:
        return f"urn:uuid:{uuid.uuid5(self.namespace, key)}"


def _defined_ids(doc: Any, out: set[str]) -> set[str]:
    if isinstance(doc, dict):
        for k, v in doc.items():
            if k == "@context":
                continue
            if k == "@id" and isinstance(v, str):
                out.add(v)
            else:
                _defined_ids(v, out)
    elif isinstance(doc, list):
        for v in doc:
            _defined_ids(v, out)
    return out


def assign_ids(
    doc: dict, meta: DatasetMeta, base_iri: str | None = None, readable: bool = False
) -> tuple[dict, IdMap]:
    """``doc`` (DDI-CDI or CDIF JSON-LD) with every node named by a ``urn:uuid:`` IRI.

    The document is rewritten in place, not copied: a download with data rows holds
    hundreds of thousands of nodes. ``base_iri`` is the dataset IRI of a CDIF document;
    it is kept, and ids anchored on it are mapped like ``#`` ids.
    """
    ids = IdMap(meta, base_iri, readable)
    defined = {v for v in _defined_ids(doc, set()) if ids.symbolic(v) is not None}

    def node(obj: dict, key: str) -> dict:
        """A node object; ``key`` is its stable key, used for the ids of its children."""
        current = obj.get("@id")
        if isinstance(current, str):
            fragment = ids.symbolic(current)
            if fragment is not None:
                obj["@id"] = ids.iri(fragment, current)
                key = ids._stable_key(fragment)[0]
            else:
                key = current
        elif not ids.readable and not _is_reference_or_value(obj):
            # A blank node: named first, as the other nodes are.
            obj = {"@id": ids.derive(key), **obj}
        for k, v in obj.items():
            if k not in _JSONLD_KEYWORDS_WITHOUT_NODES and k != "@id":
                obj[k] = value(v, f"{key}/{k}", k)
        return obj

    def value(v: Any, key: str, prop: str) -> Any:
        if isinstance(v, dict):
            if "@list" in v:
                v["@list"] = [value(x, f"{key}/{i}", prop) for i, x in enumerate(v["@list"])]
                return v
            if is_value_object(v):
                return v
            return node(v, key)
        if isinstance(v, list):
            for i, x in enumerate(v):
                v[i] = value(x, f"{key}/{i}", prop)
            return v
        if isinstance(v, str) and v in defined and prop not in _TEXT_KEYS:
            fragment = ids.symbolic(v)
            return ids.iri(fragment, v) if fragment is not None else v
        return v

    if base_iri:
        return node(doc, ""), ids
    for k, v in doc.items():
        if k != "@context":
            doc[k] = value(v, k, k)
    return doc, ids


def _is_reference_or_value(obj: dict) -> bool:
    return "@value" in obj or "@list" in obj or "@set" in obj
