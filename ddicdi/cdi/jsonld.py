"""DDI-CDI 1.1beta JSON-LD generation for wide (rectangular) datasets.

Started as a port of ``DDICDI_converter_JSONLD_incremental.py`` from the original app,
function by function, without pandas; the ids and the emission order are still those.
The vocabulary is DDI-CDI 1.1beta: the physical layer is a ``TabularTextDataSet`` with
one ``TextMapping`` per variable for a CSV upload, a ``StructuredDataSet`` (a binary
encoding) with one ``LocatorMapping`` per variable for a SAV / DTA / SAS / Parquet upload, plus a
``Segment``, each using the one ``LogicalRecord`` of the wide data set.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Iterable

from ..data import Dataset
from ..models import Concept, DatasetMeta, Variable, format_number
from . import statistics
from .codes import category, category_id, code_id, code_position_id, display_label, notation, notation_id
from .typemap import classification_level, map_to_xsd_type

CONTEXT = "https://ddi-cdi.github.io/m2t-ng/DDI-CDI_1-1beta/encoding/json-ld/ddi-cdi.jsonld"
OWL_PREFIX = {"owl": "http://www.w3.org/2002/07/owl#"}  # only added when concepts are emitted

_ELSST_RE = re.compile(r"/id/(\d+)/([0-9a-fA-F-]+)$")

Element = dict[str, Any]


@dataclass
class GenerateOptions:
    max_rows: int = 5  # rows of data included; 0 = metadata only
    process_all_rows: bool = False
    chunk_size: int = 500
    include_statistics: bool = False  # costs a qsv stats and a qsv frequency pass
    statistics_weight: str | None = None  # variable name, or "auto" for the first Weight one
    # Which statistics to emit, out of ``statistics.STATISTIC_NAMES``; None = all of them.
    statistics_include: Collection[str] | None = None


# -- physical structure -----------------------------------------------------------


def _cve(value: str) -> Element:
    return {"@type": "ControlledVocabularyEntry", "entryValue": value}


def is_tabular_text(meta: DatasetMeta) -> bool:
    """A CSV upload is a ``TabularTextDataSet``; SAV, DTA, SAS and Parquet are binary ``StructuredDataSet``s."""
    return meta.file_format == "csv"


def physical_data_set_id(meta: DatasetMeta) -> str:
    return "#tabularTextDataSet" if is_tabular_text(meta) else "#structuredDataSet"


def physical_mapping_id(meta: DatasetMeta, variable: str) -> str:
    return f"#textMapping-{variable}" if is_tabular_text(meta) else f"#locatorMapping-{variable}"


def generate_PhysicalDataSet(meta: DatasetMeta, spssfile: str) -> list[Element]:
    """The file: a ``TabularTextDataSet`` for a CSV upload, a ``StructuredDataSet`` (binary) else."""
    el: Element = {
        "@id": physical_data_set_id(meta),
        "@type": "TabularTextDataSet" if is_tabular_text(meta) else "StructuredDataSet",
        "name": {"@type": "ObjectName", "name": spssfile},
        "recordCount": meta.number_rows,
    }
    if meta.encoding:
        el["encoding"] = _cve(meta.encoding)
    if is_tabular_text(meta):
        el.update({
            "isDelimited": True,
            "isFixedWidth": False,
            "delimiter": meta.delimiter or ",",
            "hasHeader": True,
            "headerRowCount": 1,
        })
    el.update({
        "correspondsTo_DataSet": "#wideDataSet",
        "uses_LogicalRecord": "#logicalRecord",
        # no has_InstanceVariable: the variables are reached through the PhysicalMapping's
        # ``formats`` link, as in the official 1.1beta examples; the LogicalRecord lists them
        "has_Segment": ["#segment"],
        "has_SegmentPosition": ["#segmentPosition"],
        "has_PhysicalMapping": [physical_mapping_id(meta, v) for v in meta.column_names],
        "has_PhysicalMappingPosition": [f"#physicalMappingPosition-{v}" for v in meta.column_names],
    })
    return [el]


def generate_Segment(meta: DatasetMeta, spssfile: str, n_rows: int) -> list[Element]:
    el: Element = {
        "@id": "#segment",
        "@type": "Segment",
        "physicalFileName": spssfile,
        "mapsTo": "#logicalRecord",
    }
    if n_rows > 0:
        el["has_DataPoint"] = [f"#dataPoint-{i}-{v}" for v in meta.column_names for i in range(n_rows)]
        el["has_DataPointPosition"] = [
            f"#dataPointPosition-{i}-{v}" for v in meta.column_names for i in range(n_rows)
        ]
    return [el]


def generate_SegmentPosition() -> list[Element]:
    return [{"@id": "#segmentPosition", "@type": "SegmentPosition", "value": 0, "indexes": "#segment"}]


def generate_PhysicalMapping(meta: DatasetMeta) -> list[Element]:
    """How a variable is written in the file: a ``TextMapping`` in a CSV, else a ``LocatorMapping``.

    In DDI-CDI 1.1 the mapping describes the column and points at the variable, not at the
    data points, so it is emitted with or without rows. The locator of a binary file is
    the expression that finds the column in it: the variable name.

    The physical rendering lives here, not on the ``InstanceVariable``: the native print
    format (SPSS ``F8.2``, Stata ``%9.0g``, or the one synthesised for a CSV column) and the
    width and decimals read off it. The variable itself only says what kind of value it is.
    """
    text = is_tabular_text(meta)
    out: list[Element] = []
    for var in meta.variables:
        el: Element = {"@id": physical_mapping_id(meta, var.name)}
        if text:
            el["@type"] = "TextMapping"
            if var.numeric and var.decimals is not None:
                el["defaultDecimalSeparator"] = "."  # the qsv normalised copy
            el["nullSequence"] = ""  # a missing cell is left empty (see the qsv decision)
        else:
            el["@type"] = "LocatorMapping"
            el["locator"] = var.name
        if var.format:
            el["format"] = _cve(str(var.format))
            if var.width is not None:
                el["maximumLength"] = var.width
            if var.decimals is not None:
                el["decimalPositions"] = var.decimals
        el["formats"] = f"#instanceVariable-{var.name}"
        out.append(el)
    return out


def generate_PhysicalMappingPosition(meta: DatasetMeta) -> list[Element]:
    return [{
        "@id": f"#physicalMappingPosition-{v}",
        "@type": "PhysicalMappingPosition",
        "value": idx,
        "indexes": physical_mapping_id(meta, v),
    } for idx, v in enumerate(meta.column_names)]


def generate_DataPoint(meta: DatasetMeta, n_rows: int) -> list[Element]:
    return [{
        "@id": f"#dataPoint-{i}-{v}",
        "@type": "DataPoint",
        "isDescribedBy": f"#instanceVariable-{v}",
        "has_DataPoint_OF_DataSet": "#wideDataSet",
    } for v in meta.column_names for i in range(n_rows)]


def generate_DataPointPosition(meta: DatasetMeta, n_rows: int) -> list[Element]:
    return [{
        "@id": f"#dataPointPosition-{i}-{v}",
        "@type": "DataPointPosition",
        "value": i,
        "indexes": f"#dataPoint-{i}-{v}",
    } for v in meta.column_names for i in range(n_rows)]


def instance_value(var: Variable, row_idx: int, cell: str) -> Element:
    domain = "sentinelValueDomain" if var.has_missing and var.is_missing_code(cell) else "substantiveValueDomain"
    return {
        "@id": f"#instanceValue-{row_idx}-{var.name}",
        "@type": "InstanceValue",
        "content": {"@type": "TypedString", "content": cell},
        "isStoredIn": f"#dataPoint-{row_idx}-{var.name}",
        "hasValueFrom_ValueDomain": f"#{domain}-{var.name}",
    }


def generate_InstanceValue(meta: DatasetMeta, rows: list[list[str]], start_idx: int = 0) -> list[Element]:
    """Variable-major, row-minor, like the original (per chunk)."""
    out: list[Element] = []
    for col, var in enumerate(meta.variables):
        for i, row in enumerate(rows):
            cell = row[col] if col < len(row) else ""
            out.append(instance_value(var, start_idx + i, cell))
    return out


# -- logical structure ---------------------------------------------------------------


def generate_LogicalRecord(meta: DatasetMeta) -> list[Element]:
    return [{
        "@id": "#logicalRecord",
        "@type": "LogicalRecord",
        "organizes": "#wideDataSet",
        "has_InstanceVariable": [f"#instanceVariable-{v}" for v in meta.column_names],
    }]


def generate_WideDataSet(meta: DatasetMeta, spssfile: str) -> list[Element]:
    return [{
        "@id": "#wideDataSet",
        "@type": "WideDataSet",
        "name": {"@type": "ObjectName", "name": spssfile},
        "recordCount": meta.number_rows,
        "isStructuredBy": "#wideDataStructure",
        # every InstanceVariable has to be in a DataSet (SHACL minCount on the inverse)
        "has_InstanceVariable": [f"#instanceVariable-{v}" for v in meta.column_names],
    }]


def _components_for(meta: DatasetMeta, variable: str) -> list[str]:
    """Component references of one variable, in the original order (identifier, attribute, measure)."""
    r = meta.roles
    refs = []
    if variable in r.identifier:
        refs.append(f"#identifierComponent-{variable}")
    if variable in r.attribute:
        refs.append(f"#attributeComponent-{variable}")
    if variable in r.measure or not (variable in r.identifier or variable in r.attribute):
        refs.append(f"#measureComponent-{variable}")
    return refs


def generate_WideDataStructure(meta: DatasetMeta) -> list[Element]:
    el: Element = {
        "@id": "#wideDataStructure",
        "@type": "WideDataStructure",
        "has_DataStructureComponent": [],
        "has_ComponentPosition": [],
    }
    if meta.roles.identifier:
        el["has_PrimaryKey"] = "#primaryKey"
    position = 0
    for v in meta.column_names:
        for ref in _components_for(meta, v):
            el["has_DataStructureComponent"].append(ref)
            el["has_ComponentPosition"].append(f"#componentPosition-{position}")
            position += 1
    return [el]


def generate_MeasureComponent(meta: DatasetMeta) -> list[Element]:
    names = [v for v in meta.column_names if f"#measureComponent-{v}" in _components_for(meta, v)]
    return [{
        "@id": f"#measureComponent-{v}",
        "@type": "MeasureComponent",
        "isDefinedBy_RepresentedVariable": f"#instanceVariable-{v}",
    } for v in names]


def generate_IdentifierComponent(meta: DatasetMeta) -> list[Element]:
    return [{
        "@id": f"#identifierComponent-{v}",
        "@type": "IdentifierComponent",
        "isDefinedBy_RepresentedVariable": f"#instanceVariable-{v}",
    } for v in meta.roles.identifier if v in meta.column_names]


def generate_AttributeComponent(meta: DatasetMeta) -> list[Element]:
    return [{
        "@id": f"#attributeComponent-{v}",
        "@type": "AttributeComponent",
        "isDefinedBy_RepresentedVariable": f"#instanceVariable-{v}",
    } for v in meta.roles.attribute if v in meta.column_names]


def generate_PrimaryKey(meta: DatasetMeta) -> list[Element]:
    if not meta.roles.identifier:
        return []
    return [{
        "@id": "#primaryKey",
        "@type": "PrimaryKey",
        "isComposedOf": [f"#primaryKeyComponent-{v}" for v in meta.roles.identifier if v in meta.column_names],
    }]


def generate_PrimaryKeyComponent(meta: DatasetMeta) -> list[Element]:
    return [{
        "@id": f"#primaryKeyComponent-{v}",
        "@type": "PrimaryKeyComponent",
        "correspondsTo_DataStructureComponent": f"#identifierComponent-{v}",
    } for v in meta.roles.identifier if v in meta.column_names]


def generate_ComponentPosition(meta: DatasetMeta) -> list[Element]:
    out: list[Element] = []
    position = 0
    for v in meta.column_names:
        for ref in _components_for(meta, v):
            out.append({
                "@id": f"#componentPosition-{position}",
                "@type": "ComponentPosition",
                "value": position,
                "indexes": ref,
            })
            position += 1
    return out


# -- variables and value domains -----------------------------------------------------


def generate_InstanceVariable(meta: DatasetMeta, described: Collection[str] = ()) -> list[Element]:
    """``described`` names the variables that have a ``StatisticsCollection`` in the document."""
    out: list[Element] = []
    for var in meta.variables:
        el: Element = {
            "@id": f"#instanceVariable-{var.name}",
            "@type": "InstanceVariable",
            # the kind of value (double, string, int8 ...); how it is written is the PhysicalMapping's
            "physicalDataType": _cve(var.storage_type),
            "displayLabel": display_label(var.label if var.label is not None else var.name),
            "name": {"@type": "ObjectName", "name": var.name},
            "takesSubstantiveValuesFrom_SubstantiveValueDomain": f"#substantiveValueDomain-{var.name}",
        }
        if var.has_missing:
            el["takesSentinelValuesFrom"] = f"#sentinelValueDomain-{var.name}"
        if var.unit_of_measure:
            el["describedUnitOfMeasure"] = {"@type": "ControlledVocabularyEntry", "entryValue": var.unit_of_measure}
        if var.functions:
            # What the variable does in the dataset: Weight, UnitIdentifier, ...
            el["function"] = [_cve(f) for f in var.functions]
        if var.concepts:
            el["uses_Concept"] = [concept_id(var, c) for c in var.concepts]
        if var.name in described:
            el["isDescribedBy"] = statistics.statistics_collection_id(var.name)
        out.append(el)
    return out


def elsst_parts(uri: str) -> tuple[str, str]:
    """``https://elsst.cessda.eu/id/6/<uuid>`` -> ``("6", "<uuid>")``; other URIs -> ("", last segment)."""
    m = _ELSST_RE.search(uri)
    if m:
        return m.group(1), m.group(2)
    return "", uri.rstrip("/").rsplit("/", 1)[-1]


def concept_id(var: Variable, concept: Concept) -> str:
    return f"#concept-{var.name}-{elsst_parts(concept.uri)[1]}"


def generate_VariableConcept(meta: DatasetMeta) -> list[Element]:
    """One DDI-CDI ``Concept`` per variable concept, referenced by ``uses_Concept``.

    Same shape as the SoGreen provenance editor: an ELSST entry is an external
    definition (``NonDdiIdentifier`` of type ``int.cessda.elsst``) plus ``owl:sameAs``.
    """
    out: list[Element] = []
    for var in meta.variables:
        for c in var.concepts:
            version, uuid = elsst_parts(c.uri)
            name: Element = {"@type": "ObjectName"}
            if c.pref_label:
                name["name"] = c.pref_label
            ndi: Element = {"@type": "NonDdiIdentifier", "managingAgency": "ddi", "value": uuid}
            if version:
                ndi["type"] = "int.cessda.elsst"
                ndi["version"] = version
            out.append({
                "@id": concept_id(var, c),
                "@type": "Concept",
                "name": name,
                "externalDefinition": {"@type": "Reference", "nonDdiReference": ndi},
                "owl:sameAs": {"@id": c.uri},
            })
    return out


def generate_SubstantiveValueDomain(meta: DatasetMeta) -> list[Element]:
    out: list[Element] = []
    for var in meta.variables:
        el: Element = {
            "@id": f"#substantiveValueDomain-{var.name}",
            "@type": "SubstantiveValueDomain",
            "recommendedDataType": {
                "@type": "ControlledVocabularyEntry",
                "entryValue": map_to_xsd_type(var.storage_type),
            },
            "isDescribedBy": f"#substantiveValueAndConceptDescription-{var.name}",
        }
        if var.substantive_codes():
            el["takesValuesFrom"] = substantive_code_list_id(var)
        out.append(el)
    return out


def generate_SubstantiveCodeList(meta: DatasetMeta) -> list[Element]:
    return [_code_list(substantive_code_list_id(var), var, var.substantive_codes())
            for var in meta.variables if var.substantive_codes()]


def generate_SentinelValueDomain(meta: DatasetMeta) -> list[Element]:
    out: list[Element] = []
    for var in meta.variables_with_missing:
        el: Element = {
            "@id": f"#sentinelValueDomain-{var.name}",
            "@type": "SentinelValueDomain",
            "recommendedDataType": {
                "@type": "ControlledVocabularyEntry",
                "entryValue": map_to_xsd_type(var.storage_type),
            },
            "isDescribedBy": f"#sentinelValueAndConceptDescription-{var.name}",
        }
        if var.sentinel_codes():
            el["takesValuesFrom"] = sentinel_code_list_id(var)
        out.append(el)
    return out


def generate_SentinelCodeList(meta: DatasetMeta) -> list[Element]:
    return [_code_list(sentinel_code_list_id(var), var, var.sentinel_codes())
            for var in meta.variables_with_missing if var.sentinel_codes()]


def _sentinel_bounds(var: Variable) -> tuple[str | None, str | None]:
    numeric = [r for r in var.missing_ranges if r.numeric]
    if numeric:
        lo = min(float(r.lo) for r in numeric)
        hi = max(float(r.hi) for r in numeric)
        return (
            None if lo == float("-inf") else format_number(lo),
            None if hi == float("inf") else format_number(hi),
        )
    strings = [str(r.lo) for r in var.missing_ranges] + [str(r.hi) for r in var.missing_ranges]
    return min(strings), max(strings)


def generate_ValueAndConceptDescription(meta: DatasetMeta) -> list[Element]:
    out: list[Element] = [{
        "@id": f"#substantiveValueAndConceptDescription-{var.name}",
        "@type": "ValueAndConceptDescription",
        "classificationLevel": classification_level(var.measure),
    } for var in meta.variables]

    for var in meta.variables_with_missing:
        lo, hi = _sentinel_bounds(var)
        el: Element = {
            "@id": f"#sentinelValueAndConceptDescription-{var.name}",
            "@type": "ValueAndConceptDescription",
            "description": {
                "@type": "InternationalString",
                "languageSpecificString": {
                    "@type": "LanguageString",
                    "content": json.dumps([r.to_dict() for r in var.missing_ranges]),
                },
            },
        }
        if hi is not None:
            el["maximumValueExclusive"] = hi
        if lo is not None:
            el["minimumValueExclusive"] = lo
        out.append(el)
    return out


# -- code lists -------------------------------------------------------------------------
#
# A labelled code is four nodes, as DDI-CDI wants it: the ``Code`` in the list, the
# ``Category`` it denotes (the meaning), the ``Notation`` it is written with (the sign)
# and the ``CodePosition`` that keeps the order the file has. The statistics point their
# ``for`` at the very same ``Category``, which is why the ids live in ``ids.py``.


def substantive_code_list_id(var: Variable) -> str:
    return f"#substantiveCodeList-{var.name}"


def sentinel_code_list_id(var: Variable) -> str:
    return f"#sentinelCodeList-{var.name}"


def _code_list(el_id: str, var: Variable, codes: list[str]) -> Element:
    return {
        "@id": el_id,
        "@type": "CodeList",
        "allowsDuplicates": False,
        "has_Code": [code_id(var.name, c) for c in codes],
        "has_CodePosition": [code_position_id(var.name, c) for c in codes],
    }


def _labelled_codes(meta: DatasetMeta) -> Iterable[tuple[Variable, str, str]]:
    """Every labelled code of every variable, in file order, substantive ones first."""
    for var in meta.variables:
        for code in [*var.substantive_codes(), *var.sentinel_codes()]:
            yield var, code, var.value_labels[code]


def generate_Code(meta: DatasetMeta) -> list[Element]:
    return [{
        "@id": code_id(var.name, code),
        "@type": "Code",
        "denotes": category_id(var.name, code),
        "uses_Notation": notation_id(var.name, code),
    } for var, code, _ in _labelled_codes(meta)]


def generate_CodePosition(meta: DatasetMeta) -> list[Element]:
    """Positions count from 0 within their own list, so a sentinel list starts over."""
    out: list[Element] = []
    for var in meta.variables:
        for codes in (var.substantive_codes(), var.sentinel_codes()):
            for position, code in enumerate(codes):
                out.append({
                    "@id": code_position_id(var.name, code),
                    "@type": "CodePosition",
                    "value": position,
                    "indexes": code_id(var.name, code),
                })
    return out


def generate_Category(meta: DatasetMeta) -> list[Element]:
    return [category(var.name, code, label) for var, code, label in _labelled_codes(meta)]


def generate_Notation(meta: DatasetMeta) -> list[Element]:
    return [notation(var.name, code) for var, code, _ in _labelled_codes(meta)]


# -- assembly ----------------------------------------------------------------------------


def wrap_in_graph(groups: Iterable[list[Element]]) -> list[Element]:
    return [item for group in groups for item in group]


def build_document(dataset: Dataset, spssfile: str | None = None, options: GenerateOptions | None = None) -> dict:
    """Build the JSON-LD document as a Python dict."""
    options = options or GenerateOptions()
    meta = dataset.meta
    spssfile = spssfile or meta.datafile

    if options.process_all_rows:
        n_rows = meta.number_rows
        instance_values: list[Element] = []
        for start, rows in dataset.iter_chunks(options.chunk_size):
            instance_values.extend(generate_InstanceValue(meta, rows, start))
        # Row count may differ from the header count for odd files; trust the data.
        if instance_values:
            n_rows = max(n_rows, (len(instance_values) // max(len(meta.variables), 1)))
    else:
        rows = dataset.head(options.max_rows)
        n_rows = len(rows)
        instance_values = generate_InstanceValue(meta, rows, 0)

    # The statistics come first: the variables they describe get an ``isDescribedBy``.
    statistic_groups: list[list[Element]] = []
    described: list[str] = []
    if options.include_statistics:
        include = options.statistics_include
        # A selection without frequency or percentage does not need the frequency pass.
        data = statistics.collect(
            dataset, weight=options.statistics_weight, with_categories=statistics.wants_categories(include)
        )
        bundles = statistics.generate_Statistics(meta, data, include)
        described = statistics.described_variables(bundles)
        # Categories and notations for the values the code lists do not cover: a
        # frequency is computed on what is in the data, labelled or not.
        statistic_groups = [
            statistics.generate_Category(meta, data),
            statistics.generate_Notation(meta, data),
            statistics.generate_StatisticsCollection(data, bundles),
            bundles,
        ]

    groups: list[list[Element]] = [
        generate_PhysicalDataSet(meta, spssfile),
        generate_Segment(meta, spssfile, n_rows),
        generate_SegmentPosition(),
        generate_PhysicalMapping(meta),
        generate_PhysicalMappingPosition(meta),
        generate_DataPoint(meta, n_rows),
        generate_DataPointPosition(meta, n_rows),
        instance_values,
        generate_LogicalRecord(meta),
        generate_WideDataSet(meta, spssfile),
        generate_WideDataStructure(meta),
        generate_MeasureComponent(meta),
        generate_InstanceVariable(meta, described),
        generate_SubstantiveValueDomain(meta),
        generate_SubstantiveCodeList(meta),
        generate_SentinelValueDomain(meta),
        generate_SentinelCodeList(meta),
        generate_ValueAndConceptDescription(meta),
        generate_VariableConcept(meta),
        generate_Code(meta),
        generate_CodePosition(meta),
        generate_Category(meta),
        generate_Notation(meta),
    ]

    if meta.roles.identifier:
        groups += [generate_IdentifierComponent(meta), generate_PrimaryKey(meta), generate_PrimaryKeyComponent(meta)]
    if meta.roles.attribute:
        groups.append(generate_AttributeComponent(meta))
    groups.append(generate_ComponentPosition(meta))
    groups += statistic_groups

    context: Any = CONTEXT
    if any(v.concepts for v in meta.variables):
        context = [CONTEXT, OWL_PREFIX]
    return {"@context": context, "DDICDIModels": wrap_in_graph(groups)}


def generate_complete_json_ld(
    dataset: Dataset,
    spssfile: str | None = None,
    max_rows: int = 5,
    process_all_rows: bool = False,
    chunk_size: int = 500,
    include_statistics: bool = False,
    statistics_weight: str | None = None,
    statistics_include: Collection[str] | None = None,
) -> str:
    """Same entry point name as the original; returns the JSON-LD string (4-space indent)."""
    doc = build_document(
        dataset,
        spssfile,
        GenerateOptions(
            max_rows=max_rows,
            process_all_rows=process_all_rows,
            chunk_size=chunk_size,
            include_statistics=include_statistics,
            statistics_weight=statistics_weight,
            statistics_include=statistics_include,
        ),
    )
    return json.dumps(doc, indent=4, ensure_ascii=False)
