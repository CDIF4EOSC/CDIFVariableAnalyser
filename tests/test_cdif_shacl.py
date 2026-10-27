"""Validate the CDIF output against the CDIF SHACL shapes.

The shapes come from Cross-Domain-Interoperability-Framework/validation, ``ShaclValidation/``,
and are not vendored: they are looked up in ``validation/cdif/`` next to this repository or
in ``CDIF_SHACL_DIR``; a missing file skips. ``advanced=True`` because the dataset shapes
select their targets with SPARQL.
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from ddicdi.cdi.jsonld import GenerateOptions, build_document
from ddicdi.cdif import convert_document, dataset_header
from ddicdi.data import Dataset
from ddicdi.models import DatasetInfo
from ddicdi.roles import parse_roles
from tests.test_cdif import INFO

ROOT = Path(__file__).resolve().parent.parent
PROFILES = ["Discovery", "DataDescription", "DataStructure", "Complete"]


def _shapes(profile: str) -> Path:
    name = f"CDIF-{profile}-Shapes.ttl"
    for d in (ROOT / "validation" / "cdif", Path(os.environ.get("CDIF_SHACL_DIR", ROOT / "validation" / "cdif"))):
        if (d / name).exists():
            return d / name
    pytest.skip(f"{name} not found in validation/cdif; set CDIF_SHACL_DIR")


def _results(doc: dict, shapes: Path) -> list[tuple[str, str]]:
    """(severity, message) of every result."""
    pytest.importorskip("pyshacl")
    from pyshacl import validate
    from rdflib import Graph, Namespace

    sh = Namespace("http://www.w3.org/ns/shacl#")
    graph = Graph()
    graph.parse(data=json.dumps(doc), format="json-ld")
    _, report, _ = validate(graph, shacl_graph=str(shapes), inference="none", advanced=True, allow_warnings=True)
    return [
        (str(report.value(r, sh.resultSeverity)).rsplit("#", 1)[-1], str(report.value(r, sh.resultMessage)))
        for r in report.subjects(sh.resultSeverity, None)
    ]


@pytest.fixture(scope="module")
def documents(ess11):
    doc = build_document(ess11, options=GenerateOptions(max_rows=0))
    header = dataset_header(replace(ess11.meta, info=DatasetInfo.from_dict(INFO)))
    with_stats = build_document(ess11, options=GenerateOptions(max_rows=0, include_statistics=True, statistics_weight="dweight"))
    attr_meta = replace(ess11.meta, roles=parse_roles(ess11.meta, {"idno": "identifier", "essround": "attribute"}))
    with_attribute = build_document(Dataset(attr_meta, ess11.csv_path, ess11.qsv), options=GenerateOptions(max_rows=0))
    return {
        "attribute": convert_document(with_attribute, "ESS11-subset"),
        "empty": convert_document(doc, "ESS11-subset"),
        "filled": convert_document({**doc, **header}, "ESS11-subset"),
        "statistics": convert_document({**with_stats, **header}, "ESS11-subset"),
    }


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("which", ["empty", "filled", "statistics", "attribute"])
def test_no_violations(documents, which, profile):
    violations = [m for sev, m in _results(documents[which], _shapes(profile)) if sev == "Violation"]
    assert violations == []


def test_description_clears_discovery_warnings(documents):
    shapes = _shapes("Discovery")
    empty = {m for sev, m in _results(documents["empty"], shapes) if sev == "Warning"}
    filled = {m for sev, m in _results(documents["filled"], shapes) if sev == "Warning"}
    assert "At least one creator (author/originator) is recommended" in empty
    assert not {m for m in filled if "creator" in m or "Keywords" in m or "description of the resource" in m}


def test_attribute_qualifies_the_measures(documents):
    essround = next(v for v in documents["attribute"]["schema:variableMeasured"] if v["schema:name"] == "essround")
    assert essround["cdif:role"] == "Attribute"
    assert {"@id": "#instanceVariable-ppltrst"} in essround["cdif:qualifies"]
