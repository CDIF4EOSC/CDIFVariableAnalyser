"""Validate the generated document against the official DDI-CDI 1.1beta SHACL shapes.

Two files from the DDI-CDI 1.1beta release are needed and neither is vendored: the shapes
(``ddi-cdi.shacl-1-1.ttl``) and the JSON-LD context (``ddi-cdi-1-1.jsonld``, so the test
does not go to the network for it). They are looked up in ``validation/`` next to this
repository, in ``DDI_SHACL_DIR`` and in the unpacked release (``ddi-cdi-1.1beta/build``),
in that order; a missing file skips, it does not fail. Needs pyshacl (``uv sync --group dev``).

No inference: RDFS entailment adds ``rdfs:Resource`` to every node, which the shapes'
``sh:in`` lists on ``rdf:type`` then reject.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ddicdi.cdi.jsonld import GenerateOptions, build_document
from ddicdi.data import Dataset
from ddicdi.importers import import_file
from ddicdi.roles import parse_roles
from tests.cdi_files import find_context, find_shapes


@pytest.fixture(scope="module")
def shapes() -> Path:
    path = find_shapes()
    pytest.importorskip("pyshacl")
    return path


@pytest.fixture(scope="module")
def context() -> dict:
    """The local copy of the DDI-CDI context, so the test does not need the network."""
    return json.loads(find_context().read_text())["@context"]


def _validate(doc: dict, shapes: Path, context: dict) -> tuple[bool, str]:
    from pyshacl import validate
    from rdflib import Graph

    ctx = doc["@context"]
    ctx = ctx if isinstance(ctx, list) else [ctx]
    doc = {**doc, "@context": [context if isinstance(p, str) else p for p in ctx]}
    graph = Graph()
    graph.parse(data=json.dumps(doc), format="json-ld")
    conforms, _, text = validate(
        data_graph=graph, shacl_graph=str(shapes), inference="none", abort_on_first=False, allow_warnings=True
    )
    return conforms, text


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
def test_ess11_conforms(ess11, shapes, context, options):
    conforms, report = _validate(build_document(ess11, options=options), shapes, context)
    assert conforms, report


def test_variable_functions_conform(ess11, shapes, context):
    """``InstanceVariable.function`` carries what a variable does in the dataset."""
    meta = copy.deepcopy(ess11.meta)  # the ess11 fixture is session scoped
    meta.var("dweight").functions = ["Weight"]
    meta.var("idno").functions = ["UnitIdentifier"]
    doc = build_document(Dataset(meta, ess11.csv_path, ess11.qsv), options=GenerateOptions(max_rows=0))
    conforms, report = _validate(doc, shapes, context)
    assert conforms, report


def test_attribute_qualifies_conforms(ess11, shapes, context):
    """An attribute ``qualifies`` the measure components."""
    meta = copy.deepcopy(ess11.meta)
    meta.roles = parse_roles(meta, {"idno": "identifier", "essround": "attribute"})
    doc = build_document(Dataset(meta, ess11.csv_path, ess11.qsv), options=GenerateOptions(max_rows=0))
    attr = next(e for e in doc["DDICDIModels"] if e["@id"] == "#attributeComponent-essround")
    assert "#measureComponent-ppltrst" in attr["qualifies"] and "#measureComponent-essround" not in attr["qualifies"]
    conforms, report = _validate(doc, shapes, context)
    assert conforms, report


@pytest.mark.parametrize("include_statistics", [False, True], ids=["plain", "statistics"])
def test_csv_upload_conforms(qsv, tmp_path, work_dir, shapes, context, include_statistics):
    """A CSV is a ``TabularTextDataSet`` with a ``TextMapping`` per column."""
    csv = work_dir / "t.csv"
    csv.write_text("a;b\n1;x\n2;y\n99;\n")
    ds = import_file(csv, tmp_path / "out", qsv)
    doc = build_document(ds, options=GenerateOptions(max_rows=2, include_statistics=include_statistics))
    assert next(e for e in doc["DDICDIModels"] if e["@id"] == "#tabularTextDataSet")["@type"] == "TabularTextDataSet"
    conforms, report = _validate(doc, shapes, context)
    assert conforms, report
