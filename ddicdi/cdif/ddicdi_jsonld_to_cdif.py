#!/usr/bin/env python3
"""
ddicdi_jsonld_to_cdif.py - Convert DDI-CDI JSON-LD instances to CDIF JSON-LD.

Vendored from the CDIF converters repository (Apache-2.0),
https://github.com/Cross-Domain-Interoperability-Framework/converters
``DDI-CDI/ddicdi_jsonld_to_cdif.py`` at commit 0f281da, and extended for the
DDI-CDI 1.1beta JSON-LD that DDI-CDI Studio writes. Changes against upstream
(meant to go back as a pull request):

  - InstanceVariable displayLabel -> schema:description (definition is the
    fallback); uses_Concept -> cdif:uses; describedUnitOfMeasure ->
    cdif:simpleUnitOfMeasure.
  - Substantive and sentinel value domains with a CodeList ->
    cdi:takesSubstantiveValuesFrom / cdi:takesSentinelValuesFrom, each a
    cdif:EnumerationDomain referencing a skos:ConceptScheme (ported from
    ``ddicdi_to_cdif.py``, phases 2 and 6).
  - StructuredDataSet + LocatorMapping (binary SPSS, Stata, SAS, Parquet files)
    -> a distribution typed cdi:StructuredDataSet with cdif:LocatorMapping
    entries (cdi:locator) and the record count.
  - PrimaryKey -> an inline cdif:Key, as ``ddicdi_to_cdif.py`` builds it.
  - The constants come from ``ddicdi_to_cdif.py`` and are copied here, so the
    XML reader is not needed; conformance detection (the ``validation``
    submodule) is left out; the built-in conformsTo gains data_structure when
    the distribution has a structure.
  - ``convert_document()`` takes the parsed document instead of a path.

Reads the compact JSON-LD serialisation of DDI-CDI (1.1beta context,
``https://ddi-cdi.github.io/m2t-ng/DDI-CDI_1-1beta/encoding/json-ld/ddi-cdi.jsonld``)
as written by the CODATA DDI-CDI export (https://ai.codata.org/export): a
dataset-level header in Dublin Core / schema.org / PROV terms, plus a flat
``DDICDIModels`` list of typed objects linked by local ``#...`` ids.

The objects are read as plain JSON (no JSON-LD expansion): every object is
indexed by its ``@id`` and references are followed by id, the same way
``ddicdi_to_cdif.py`` reassembles the XML serialisation.

  header dct:title / description / license / language -> schema:name / ...
  header dct:identifier                       -> schema:identifier
  header dct:isPartOf                         -> schema:isPartOf
  header prov:wasDerivedFrom                  -> prov:wasDerivedFrom, and the
                                                 distribution's contentUrl
  header schema:contentSize / checksum        -> distribution contentSize /
                                                 spdx:checksum
  InstanceVariable                            -> schema:variableMeasured
    name, displayLabel (or definition when not just the name),
    classificationLevel, cdif:role (from the MeasureComponent etc. that it
    defines), SubstantiveValueDomain/recommendedDataType -> cdif:physicalDataType
    (xsd IRI), code lists -> skos:ConceptScheme
  TabularTextDataSet                          -> distribution typed
                                                 cdi:TabularTextDataSet:
    isDelimited, isFixedWidth, delimiter, hasHeader, headerRowCount,
    recordCount -> countRows, variable count -> countColumns
  StructuredDataSet                           -> distribution typed
                                                 cdi:StructuredDataSet
  TextMapping / LocatorMapping + PhysicalMappingPosition
                                              -> cdif:hasPhysicalMapping
                                                 (cdif:TextMapping /
                                                 cdif:LocatorMapping)
  WideDataStructure + components + positions  -> cdi:isStructuredBy
  PrimaryKey                                  -> cdif:has_PrimaryKey (cdif:Key)

Out of scope: DataPoint / DataPointPosition / InstanceValue (a sample of the
data values) - CDIF is a metadata framework.

Usage:
    python ddicdi_jsonld_to_cdif.py Examples/107910_DVN_CWOZTP.jsonLD -o out.json
"""
import argparse
import json
from pathlib import Path

# From ddicdi_to_cdif.py.
CDI_CTX = {
    "schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "cdif": "https://w3id.org/cdif/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "prov": "http://www.w3.org/ns/prov#",
}

# DDI-CDI DataStructureComponent type -> CDIF cdif:role (values must be
# members of the cdif:role enum: UnitIdentifier | Measure | Attribute |
# Dimension | Descriptor | ReferenceVariable).
COMPONENT_ROLE = {
    "IdentifierComponent": "UnitIdentifier",
    "MeasureComponent": "Measure",
    "DimensionComponent": "Dimension",
    "AttributeComponent": "Attribute",
    "VariableDescriptorComponent": "Descriptor",
    "VariableValueComponent": "Measure",
}

# DDI-CDI DataStructure subtypes.
STRUCTURE_TYPES = ("WideDataStructure", "LongDataStructure",
                   "DimensionalDataStructure", "DataStructure")

NIL_MISSING = "http://www.opengis.net/def/nil/OGC/0/missing"
UNKNOWN_DATE = "1900-01-01"
XSD = "http://www.w3.org/2001/XMLSchema#"
# The export names XML Schema datatypes by their spec anchor
# (https://www.w3.org/TR/xmlschema-2/#decimal); CDIF wants the datatype IRI.
XSD_DOC = "https://www.w3.org/TR/xmlschema-2/#"
DDI_DISCOVERY = "http://rdf-vocabulary.ddialliance.org/discovery#"

# Media types for the binary files a StructuredDataSet describes, by extension.
ENCODING_FORMATS = {
    ".sav": "application/x-spss-sav",
    ".zsav": "application/x-spss-sav",
    ".dta": "application/x-stata-dta",
    ".sas7bdat": "application/x-sas-data",
    ".parquet": "application/vnd.apache.parquet",
}


def value(node, *path):
    """Follow keys through nested dicts; return the leaf or None."""
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def by_type(objects, *types):
    return [o for o in objects if o.get("@type") in types]


def position_map(objects, pos_type):
    """{indexed object id: value} for a DDI-CDI *Position class."""
    return {o["indexes"]: o["value"] for o in by_type(objects, pos_type)
            if "indexes" in o and "value" in o}


def as_list(x):
    return x if isinstance(x, list) else [] if x is None else [x]


def xsd_iri(dt):
    if dt and dt.startswith(XSD_DOC):
        return XSD + dt[len(XSD_DOC):]
    return dt


def label_of(node):
    """The text of a displayLabel (a LabelForDisplay's LanguageString)."""
    return value(node, "displayLabel", "languageSpecificString", "content")


def build_concept_scheme(codelist, index, code_order):
    """CodeList (has_Code -> Code -> Category + Notation) -> skos:ConceptScheme.

    As in ``ddicdi_to_cdif.py``: CDIF wants an identifier, a label, a
    modification date, a licence and at least one concept; DDI-CDI gives no
    date or licence, so those take the unknown values. Every concept carries a
    notation and a label; a code without a value label is labelled by its
    notation. Returns None for a CodeList with no codes.
    """
    scheme_id = codelist["@id"]
    local_id = scheme_id.lstrip("#")
    scheme = {"@type": ["skos:ConceptScheme"], "@id": scheme_id,
              "schema:identifier": local_id,
              "skos:prefLabel": value(codelist, "name", "name") or local_id,
              "schema:dateModified": UNKNOWN_DATE,
              "schema:license": [NIL_MISSING]}
    codes = sorted(as_list(codelist.get("has_Code")),
                   key=lambda c: code_order.get(c, 1_000_000))
    concepts = []
    for cid in codes:
        code = index.get(cid)
        if code is None:
            continue
        cat = index.get(code.get("denotes"))
        notation = value(index.get(code.get("uses_Notation")), "content", "content")
        prefl = label_of(cat) or value(cat, "name", "name") or notation
        concept = {"@type": ["skos:Concept"], "@id": cid,
                   "skos:inScheme": [{"@id": scheme_id}]}
        if notation is not None:
            concept["skos:notation"] = str(notation)
        if prefl is not None:
            concept["skos:prefLabel"] = str(prefl)
        concepts.append(concept)
    if not concepts:
        return None
    scheme["skos:hasTopConcept"] = concepts
    return scheme


def value_domain(domain, index, code_order, substantive):
    """A value domain with a code list -> a cdif Substantive/SentinelValueDomain."""
    codelist = index.get(value(domain, "takesValuesFrom"))
    if codelist is None or codelist.get("@type") != "CodeList":
        return None
    scheme = build_concept_scheme(codelist, index, code_order)
    if scheme is None:
        return None
    return {"@type": ["cdif:SubstantiveValueDomain" if substantive
                      else "cdif:SentinelValueDomain"],
            "cdif:takesValuesFrom": {"@type": ["cdif:EnumerationDomain"],
                                     "cdif:references": scheme}}


def build_variable(iv, roles, index, code_order):
    name = value(iv, "name", "name") or iv["@id"].lstrip("#")
    vm = {"@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
          "@id": iv["@id"], "schema:name": name}
    description = label_of(iv) or value(iv, "definition", "content")
    if description and description != name:
        vm["schema:description"] = description
    if iv["@id"] in roles:
        vm["cdif:role"] = roles[iv["@id"]]
    unit = value(iv, "describedUnitOfMeasure", "entryValue")
    if unit:
        vm["cdif:simpleUnitOfMeasure"] = unit
    concepts = [value(index.get(c), "owl:sameAs", "@id") for c in as_list(iv.get("uses_Concept"))]
    if any(concepts):
        vm["cdif:uses"] = [{"@id": c} for c in concepts if c]
    svd = index.get(iv.get("takesSubstantiveValuesFrom_SubstantiveValueDomain"))
    if svd:
        dt = xsd_iri(value(svd, "recommendedDataType", "entryValue"))
        if dt:
            vm["cdif:physicalDataType"] = {"@id": dt}
        level = value(index.get(svd.get("isDescribedBy")), "classificationLevel")
        if level:
            vm["cdi:classificationLevel"] = level
        domain = value_domain(svd, index, code_order, substantive=True)
        if domain:
            vm["cdi:takesSubstantiveValuesFrom"] = domain
    sentinels = []
    for ref in as_list(iv.get("takesSentinelValuesFrom")
                       or iv.get("takesSentinelValuesFrom_SentinelValueDomain")):
        domain = value_domain(index.get(ref), index, code_order, substantive=False)
        if domain:
            sentinels.append(domain)
    if sentinels:
        vm["cdi:takesSentinelValuesFrom"] = sentinels
    return vm


def build_role_map(objects):
    """{InstanceVariable id: cdif:role} from the components that it defines."""
    roles = {}
    for comp in by_type(objects, *COMPONENT_ROLE):
        var = comp.get("isDefinedBy_RepresentedVariable")
        if var:
            roles[var] = COMPONENT_ROLE[comp["@type"]]
    return roles


def build_primary_key(pk, index):
    """PrimaryKey -> an inline cdif:Key (cdif:has_PrimaryKey takes the Key
    itself, not a reference to it), as in ``ddicdi_to_cdif.py``.

    PrimaryKey isComposedOf -> PrimaryKeyComponent correspondsTo_DataStructureComponent
    -> component isDefinedBy_RepresentedVariable -> variable. Positions follow
    the order of the PrimaryKeyComponents. None when no component resolves.
    """
    if pk is None:
        return None
    positions = []
    for pkc_id in as_list(pk.get("isComposedOf")):
        comp = index.get(value(index.get(pkc_id), "correspondsTo_DataStructureComponent"))
        var = value(comp, "isDefinedBy_RepresentedVariable")
        if var:
            positions.append({"@type": ["cdi:ComponentPosition"],
                              "cdi:indexes": {"@id": var},
                              "cdi:value": len(positions) + 1})
    if not positions:
        return None
    return {"@type": ["cdif:Key"], "@id": pk["@id"], "cdif:isComposedOf": positions}


def build_data_structure(objects, index):
    struct = next(iter(by_type(objects, *STRUCTURE_TYPES)), None)
    if struct is None:
        return None
    order = position_map(objects, "ComponentPosition")
    comp_ids = sorted(as_list(struct.get("has_DataStructureComponent")),
                      key=lambda c: order.get(c, 1_000_000))
    components = []
    for cid in comp_ids:
        comp = index.get(cid)
        if comp is None:
            continue
        node = {"@type": ["cdi:" + comp["@type"]], "@id": cid}
        var = comp.get("isDefinedBy_RepresentedVariable")
        if var:
            node["cdif:isDefinedBy_Variable"] = {"@id": var}
        components.append(node)
    node = {"@type": ["cdi:" + struct["@type"]], "@id": struct["@id"]}
    if components:
        node["cdi:has_DataStructureComponent"] = components
    key = build_primary_key(index.get(struct.get("has_PrimaryKey")), index)
    if key is not None:
        node["cdif:has_PrimaryKey"] = key
    return node


def build_physical_mappings(objects, index):
    """TextMapping -> cdif:TextMapping and LocatorMapping -> cdif:LocatorMapping,
    ordered by PhysicalMappingPosition.

    The export gives every column the same nullSequence list (its own default
    set of null tokens); cdi:nullSequence takes a single string, so it is not
    carried over.
    """
    order = position_map(objects, "PhysicalMappingPosition")
    mappings = []
    for tm in by_type(objects, "TextMapping", "LocatorMapping"):
        entry = {"@type": ["cdif:" + tm["@type"]]}
        if tm["@id"] in order:
            entry["cdif:index"] = order[tm["@id"]]
        if tm.get("locator"):
            entry["cdi:locator"] = tm["locator"]
        fmt = value(tm, "format", "entryValue")
        if fmt:
            entry["cdif:format"] = fmt
        var = index.get(tm.get("formats"))
        pdt = value(var, "physicalDataType", "entryValue")
        if pdt:
            entry["cdif:physicalDataType"] = pdt
        for key in ("minimumLength", "maximumLength"):
            if key in tm:
                entry["cdi:" + key] = tm[key]
        if tm.get("formats"):
            entry["cdif:formats_InstanceVariable"] = {"@id": tm["formats"]}
        mappings.append(entry)
    mappings.sort(key=lambda m: m.get("cdif:index", 1_000_000))
    return mappings


def count_property(name, concept, n):
    return {"@type": ["schema:PropertyValue"],
            "schema:propertyID": [DDI_DISCOVERY + concept],
            "schema:name": name, "schema:value": n}


def build_distribution(header, objects, index, nvars):
    ttd = next(iter(by_type(objects, "TabularTextDataSet")), {})
    sds = next(iter(by_type(objects, "StructuredDataSet")), {})
    physical = ttd or sds
    segment = next(iter(by_type(objects, "Segment")), {})
    dist = {"@type": ["schema:DataDownload"],
            "schema:name": (segment.get("physicalFileName")
                            or value(physical, "name", "name")
                            or header.get("dct:title"))}
    # The export records the file it read as prov:wasDerivedFrom; for a
    # Dataverse file that is its download (api/access/datafile) URL.
    source = value(header, "prov:wasDerivedFrom", "@id")
    dist["schema:contentUrl"] = source or NIL_MISSING
    if ttd.get("isDelimited") and ttd.get("delimiter") == ",":
        dist["schema:encodingFormat"] = ["text/csv"]
    elif sds and dist["schema:name"]:
        media = ENCODING_FORMATS.get(Path(dist["schema:name"]).suffix.lower())
        if media:
            dist["schema:encodingFormat"] = [media]
    if "schema:contentSize" in header:
        dist["schema:contentSize"] = str(header["schema:contentSize"])
    checksum = header.get("schema:checksum")
    if checksum and checksum.get("schema:checksumValue"):
        dist["spdx:checksum"] = {
            "@type": ["spdx:Checksum"],
            "spdx:algorithm": checksum.get("schema:algorithm", ""),
            "spdx:checksumValue": checksum["schema:checksumValue"]}

    if ttd:
        dist["@type"].append("cdi:TabularTextDataSet")
        for key in ("isDelimited", "isFixedWidth", "delimiter", "hasHeader",
                    "headerRowCount"):
            if key in ttd:
                dist["cdi:" + key] = ttd[key]
    elif sds:
        # A binary file read by column name: its mappings are LocatorMappings.
        dist["@type"].append("cdi:StructuredDataSet")
    if physical:
        counts = []
        if "recordCount" in physical:
            counts.append(count_property("countRows", "caseQuantity",
                                         physical["recordCount"]))
        if nvars:
            counts.append(count_property("countColumns", "variableQuantity", nvars))
        if counts:
            dist["schema:additionalProperty"] = counts

    # The structure needs no extra @type: data_structure asks only for a
    # DataDownload with cdi:isStructuredBy. cdi:StructuredDataSet would be wrong
    # for a delimited file -- in CDIF it marks a file whose mappings are
    # LocatorMappings, not one with TextMappings.
    structure = build_data_structure(objects, index)
    if structure is not None:
        dist["cdi:isStructuredBy"] = structure
    mappings = build_physical_mappings(objects, index)
    if mappings:
        dist["cdif:hasPhysicalMapping"] = mappings
    return dist


def build_catalog_record(dataset_iri, name, source_conforms):
    note = ("Metadata converted to CDIF by ddicdi_jsonld_to_cdif.py from a "
            "DDI-CDI JSON-LD description")
    if source_conforms:
        note += f" (dct:conformsTo {source_conforms})"
    note += (". The data sample in the source (DataPoint / InstanceValue) is "
             "not carried over.")
    return {
        "@type": ["schema:Dataset"],
        "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
        "@id": dataset_iri + "#cdif-catalog-record",
        "schema:name": f"Metadata record for: {name[:120]}",
        "schema:about": {"@id": dataset_iri},
        "schema:description": note,
        "dcterms:conformsTo": [
            {"@id": "https://w3id.org/cdif/core/1.1"},
            {"@id": "https://w3id.org/cdif/discovery/1.1"},
            {"@id": "https://w3id.org/cdif/data_description/1.1"}],
    }


def convert_document(header, stem, explicit_id=None):
    """Convert a parsed DDI-CDI JSON-LD document; ``stem`` names it when the
    header has no @id or title."""
    header = dict(header)
    objects = header.pop("DDICDIModels", [])
    index = {o["@id"]: o for o in objects if "@id" in o}
    code_order = position_map(objects, "CodePosition")

    roles = build_role_map(objects)
    variables = [build_variable(o, roles, index, code_order)
                 for o in by_type(objects, "InstanceVariable")]

    iri = explicit_id or header.get("@id") or f"urn:ddi-cdi:{stem}"
    name = header.get("dct:title") or value(
        next(iter(by_type(objects, "WideDataSet")), {}), "name", "name") or stem

    doc = {"@context": dict(CDI_CTX, spdx="http://spdx.org/rdf/terms#"),
           "@id": iri, "@type": ["schema:Dataset"], "schema:name": name}
    if header.get("dct:description"):
        doc["schema:description"] = header["dct:description"]
    doc["schema:identifier"] = {"@type": ["schema:PropertyValue"],
                                "schema:value": header.get("dct:identifier") or iri}
    # No modification date in the source; the converters' placeholder.
    doc["schema:dateModified"] = UNKNOWN_DATE
    doc["schema:license"] = [header.get("dct:license") or NIL_MISSING]
    if header.get("dct:language"):
        doc["schema:inLanguage"] = header["dct:language"]
    parts = [p for p in as_list(header.get("dct:isPartOf")) if value(p, "@id")]
    if parts:
        doc["schema:isPartOf"] = [{"@id": p["@id"]} for p in parts]
    if value(header, "prov:wasDerivedFrom", "@id"):
        doc["prov:wasDerivedFrom"] = [{"@id": header["prov:wasDerivedFrom"]["@id"]}]
    if variables:
        doc["schema:variableMeasured"] = variables
    doc["schema:distribution"] = [
        build_distribution(header, objects, index, len(variables))]
    doc["schema:subjectOf"] = build_catalog_record(
        iri, name, header.get("dct:conformsTo"))
    # What detect_conformance would add: a structured distribution is data_structure.
    if "cdi:isStructuredBy" in doc["schema:distribution"][0]:
        doc["schema:subjectOf"]["dcterms:conformsTo"].append(
            {"@id": "https://w3id.org/cdif/data_structure/1.1"})
    return doc


def convert(path, explicit_id=None):
    header = json.loads(Path(path).read_text(encoding="utf-8"))
    return convert_document(header, Path(path).stem, explicit_id)


def main():
    ap = argparse.ArgumentParser(
        description="Convert DDI-CDI JSON-LD instances to CDIF JSON-LD")
    ap.add_argument("input", help="Input DDI-CDI JSON-LD file (with DDICDIModels)")
    ap.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    ap.add_argument("--id", dest="explicit_id",
                    help="Explicit dataset IRI for @id (default: the source @id)")
    args = ap.parse_args()

    doc = convert(args.input, explicit_id=args.explicit_id)
    out = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Written: {args.output} "
              f"({len(doc.get('schema:variableMeasured', []))} vars)")
    else:
        print(out)


if __name__ == "__main__":
    main()
