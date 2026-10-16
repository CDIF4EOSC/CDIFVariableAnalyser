"""Every ``@type`` and every property in the document is a term of the DDI-CDI 1.1beta context.

The SHACL shapes are closed, so a stray key fails validation; this test finds the same
mistakes without pyshacl and names them ``(id, type, key)``. The context is the release's
combined ``ddi-cdi.jsonld``: one entry per class, inheriting through ``"Parent.jsonld"``.
"""

from __future__ import annotations

import json
from functools import lru_cache

import pytest

from ddicdi.cdi.jsonld import GenerateOptions, build_document
from ddicdi.importers import import_file
from tests.cdi_files import find_context

IGNORED = {"@id", "@type", "owl:sameAs"}


@pytest.fixture(scope="module")
def context() -> dict:
    return json.loads(find_context().read_text())["@context"]


@lru_cache(maxsize=None)
def _terms(context_id: int, cls: str) -> frozenset[str] | None:
    """The terms a class may carry, its parents' included; None for an unknown class."""
    context = _CONTEXTS[context_id]
    entry = context.get(cls)
    if not isinstance(entry, dict):
        return None
    terms: set[str] = set()
    for part in entry["@context"]:
        if isinstance(part, str):
            terms |= _terms(context_id, part.removesuffix(".jsonld")) or set()
        else:
            terms |= {k for k in part if not k.startswith("@") and k not in ("cdi", "xsd", " comment ")}
    return frozenset(terms)


_CONTEXTS: dict[int, dict] = {}


def offenders(doc: dict, context: dict) -> list[tuple[str, str, str]]:
    _CONTEXTS[id(context)] = context
    out: list[tuple[str, str, str]] = []

    def walk(obj, owner: str):
        if isinstance(obj, list):
            for x in obj:
                walk(x, owner)
            return
        if not isinstance(obj, dict):
            return
        cls = obj.get("@type")
        if cls is None:
            return
        terms = _terms(id(context), cls)
        if terms is None:
            out.append((owner, cls, "@type"))
            return
        for key, value in obj.items():
            if key in IGNORED:
                continue
            if key not in terms:
                out.append((obj.get("@id", owner), cls, key))
            walk(value, obj.get("@id", owner))

    for el in doc["DDICDIModels"]:
        walk(el, el.get("@id", "?"))
    return out


@pytest.mark.parametrize(
    "options",
    [
        pytest.param(GenerateOptions(max_rows=2), id="rows"),
        pytest.param(GenerateOptions(max_rows=0), id="metadata-only"),
        pytest.param(GenerateOptions(max_rows=2, include_statistics=True), id="statistics"),
        pytest.param(
            GenerateOptions(max_rows=0, include_statistics=True, statistics_weight="dweight"),
            id="statistics-weighted",
        ),
    ],
)
def test_ess11_uses_only_context_terms(ess11, context, options):
    assert offenders(build_document(ess11, options=options), context) == []


def test_csv_upload_uses_only_context_terms(qsv, tmp_path, work_dir, context):
    csv = work_dir / "t.csv"
    csv.write_text("a;b\n1;x\n2;y\n")
    ds = import_file(csv, tmp_path / "out", qsv)
    doc = build_document(ds, options=GenerateOptions(max_rows=2, include_statistics=True))
    assert offenders(doc, context) == []
