"""CDIF read back from the store -> the editor's workspace (Open from QLever, step a).

The inverse of the CDIF output (``header.py`` + ``ddicdi_jsonld_to_cdif.py``), on the RDF
graph of one saved document. CDIF is a lossy projection of the editor's DDI-CDI, so the
round trip is not complete. What does not come back:

* the data (CDIF carries no rows). The statistics do come back, as saved: they stand in
  for qsv's until the session has rows (``saved_statistics.py``), rounded at about the
  12th significant digit by QLever;
* the missing-value ranges: only labelled missing codes are in CDIF, and they come back
  as single missing values;
* a missing value without a label, and the labels of concepts (only their IRIs);
* the order of keywords and contributors (RDF sets; sorted here), and of value labels
  (sorted by code);
* the file label and encoding of the source file, and its delimiter's quote rules;
* fields left empty and written as a stand-in (licence "missing", 1900-01-01): empty again.

``tests/test_open_from_qlever.py`` lists what a save -> open -> save changes.
"""

from __future__ import annotations

from pathlib import Path

from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection

from ..models import Agent, Concept, DatasetInfo, DatasetMeta, Grant, MissingRange, Roles, Variable
from .ddicdi_jsonld_to_cdif import NIL_MISSING, UNKNOWN_DATE

SCHEMA = Namespace("http://schema.org/")
CDIF = Namespace("https://w3id.org/cdif/")  # cdif:index and cdif:format by item: CDIF.index is str.index
CDI = Namespace("http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/")
SKOS = Namespace("http://www.w3.org/2004/02/skos/core#")
SPDX = Namespace("http://spdx.org/rdf/terms#")
DCAT = Namespace("http://www.w3.org/ns/dcat#")

_ROLES = {"UnitIdentifier": "identifier", "Attribute": "attribute", "Measure": "measure"}
_MEASURES = {"Continuous": "scale", "Ordinal": "ordinal", "Nominal": "nominal"}
# xsd type -> storage type, when the physical mapping does not name one
_STORAGE = {"int": "int32", "integer": "int32", "long": "int64", "short": "int16", "byte": "int8",
            "double": "double", "float": "float", "decimal": "double", "dateTime": "datetime",
            "date": "date", "boolean": "bool", "string": "string"}
_FILE_FORMATS = {".sav": "spss", ".zsav": "spss", ".por": "spss", ".dta": "stata", ".sas7bdat": "sas",
                 ".xpt": "sas", ".parquet": "parquet", ".csv": "csv", ".tsv": "csv", ".txt": "csv"}


class NotADocument(ValueError):
    pass


def _str(g: Graph, s, p) -> str:
    v = g.value(s, p)
    return str(v) if v is not None else ""


def _int(g: Graph, s, p) -> int | None:
    v = g.value(s, p)
    try:
        return int(float(v)) if v is not None else None
    except (TypeError, ValueError):
        return None


def _dataset_node(g: Graph) -> URIRef:
    """The schema:Dataset that is the document (not its catalog record)."""
    for s in g.subjects(SCHEMA.distribution, None):
        if (s, RDF.type, SCHEMA.Dataset) in g:
            return s
    raise NotADocument("No CDIF dataset (schema:Dataset with a distribution) in the graph")


def _uuid_of(iri) -> str | None:
    text = str(iri)
    return text[len("urn:uuid:"):] if text.startswith("urn:uuid:") else None


# -- the dataset description -----------------------------------------------------------


def _identifier(g: Graph, node) -> str:
    """A schema:identifier: an IRI or text, or a PropertyValue."""
    if node is None:
        return ""
    if isinstance(node, Literal) or (isinstance(node, URIRef) and (node, RDF.type, None) not in g):
        return str(node)
    return _str(g, node, SCHEMA.url) or _str(g, node, SCHEMA.value)


def _agent(g: Graph, node, role: str = "") -> Agent:
    org = (node, RDF.type, SCHEMA.Organization) in g
    agent = Agent(name=_str(g, node, SCHEMA.name), kind="organization" if org else "person",
                  identifier=_identifier(g, g.value(node, SCHEMA.identifier)), role=role)
    affiliation = g.value(node, SCHEMA.affiliation)
    if affiliation is not None:
        agent.affiliation = _str(g, affiliation, SCHEMA.name)
        agent.affiliation_id = _identifier(g, g.value(affiliation, SCHEMA.identifier))
    contact = g.value(node, SCHEMA.contactPoint)
    if contact is not None:
        agent.email = _str(g, contact, SCHEMA.email)
    return agent


def _contributor(g: Graph, node) -> Agent:
    if (node, RDF.type, SCHEMA.Role) in g:
        term = g.value(node, SCHEMA.roleName)  # a DefinedTerm with the code, or the code itself
        role = str(term) if isinstance(term, Literal) else _str(g, term, SCHEMA.termCode)
        return _agent(g, g.value(node, SCHEMA.contributor), role)
    return _agent(g, node)


def _grant(g: Graph, node) -> Grant:
    grant = Grant(title=_str(g, node, SCHEMA.name))
    ident = g.value(node, SCHEMA.identifier)
    if ident is not None:
        grant.award = _str(g, ident, SCHEMA.value) or str(ident)
    funder = g.value(node, SCHEMA.funder)
    if funder is not None:
        grant.funder = _str(g, funder, SCHEMA.name)
        grant.funder_id = _identifier(g, g.value(funder, SCHEMA.identifier))
        if grant.funder == grant.funder_id:  # the converter names an unnamed funder by its id
            grant.funder = ""
    return grant


def _info(g: Graph, ds, dist) -> DatasetInfo:
    info = DatasetInfo(
        title=_str(g, ds, SCHEMA.name),
        description=_str(g, ds, SCHEMA.description),
        url=_str(g, ds, SCHEMA.url),
        record_id=str(ds),
        version=_str(g, ds, SCHEMA.version),
        language=_str(g, ds, SCHEMA.inLanguage),
        date_published=_str(g, ds, SCHEMA.datePublished),
        date_modified=_str(g, ds, SCHEMA.dateModified),
    )
    if info.date_modified == UNKNOWN_DATE:
        info.date_modified = ""
    licence = _str(g, ds, SCHEMA.license)
    info.license = "" if licence == NIL_MISSING else licence
    ident = _identifier(g, g.value(ds, SCHEMA.identifier))
    info.identifier = "" if ident == str(ds) else ident  # the converter falls back to the record IRI
    content = _str(g, dist, SCHEMA.contentUrl) if dist is not None else ""
    info.content_url = "" if content == NIL_MISSING else content
    info.keywords = sorted(str(k) for k in g.objects(ds, SCHEMA.keywords))
    creators = g.value(ds, SCHEMA.creator)
    if creators is not None:
        members = list(Collection(g, creators)) if (creators, RDF.first, None) in g else [creators]
        info.creators = [_agent(g, a) for a in members]
    publisher = g.value(ds, SCHEMA.publisher)
    if publisher is not None:
        info.publisher = _agent(g, publisher)
    info.contributors = sorted((_contributor(g, c) for c in g.objects(ds, SCHEMA.contributor)),
                               key=lambda a: a.name)
    for period in g.objects(ds, SCHEMA.temporalCoverage):
        if isinstance(period, Literal) and "/" in str(period):
            start, end = str(period).split("/", 1)
            info.temporal_start, info.temporal_end = ("" if start == ".." else start), ("" if end == ".." else end)
    info.spatial = sorted(_str(g, p, SCHEMA.name) for p in g.objects(ds, SCHEMA.spatialCoverage))
    info.funding = [_grant(g, f) for f in g.objects(ds, SCHEMA.funding)]
    return info


# -- the variables ---------------------------------------------------------------------


def _codes(g: Graph, domain) -> dict[str, str]:
    """A value domain -> {code: label} from its concept scheme."""
    out: dict[str, str] = {}
    if domain is None:
        return out
    enumeration = g.value(domain, CDIF.takesValuesFrom)
    scheme = g.value(enumeration, CDIF.references) if enumeration is not None else None
    if scheme is None:
        return out
    for concept in g.objects(scheme, SKOS.hasTopConcept):
        notation = _str(g, concept, SKOS.notation)
        if notation:
            out[notation] = _str(g, concept, SKOS.prefLabel) or notation
    return out


def _code_key(code: str):
    try:
        return (0, float(code), code)
    except ValueError:
        return (1, 0.0, code)


def _variable(g: Graph, node, mapping) -> Variable:
    name = _str(g, node, SCHEMA.name)
    var = Variable(name=name, label=_str(g, node, SCHEMA.description) or None)
    uid = _uuid_of(node)
    if uid:
        var.uid = uid
    storage = _str(g, mapping, CDIF.physicalDataType) if mapping is not None else ""
    if not storage:
        xsd = _str(g, node, CDIF.physicalDataType).rsplit("#", 1)[-1]
        storage = _STORAGE.get(xsd, "string")
    var.storage_type = storage
    var.numeric = storage != "string" and not storage.startswith(("date", "time"))
    if mapping is not None:
        var.format = _str(g, mapping, CDIF["format"])
    var.measure = _MEASURES.get(_str(g, node, CDI.classificationLevel), "unknown")
    var.functions = sorted(str(f) for f in g.objects(node, CDIF.function))
    unit = g.value(node, CDIF.describedUnitOfMeasure) or g.value(node, CDIF.simpleUnitOfMeasure)
    var.unit_of_measure = str(unit) if unit is not None else None
    var.concepts = [Concept(uri=str(c)) for c in sorted(g.objects(node, CDIF.uses), key=str)]

    labels = _codes(g, g.value(node, CDI.takesSubstantiveValuesFrom))
    missing: dict[str, str] = {}
    for domain in g.objects(node, CDI.takesSentinelValuesFrom):
        missing.update(_codes(g, domain))
    labels.update(missing)
    var.value_labels = {code: labels[code] for code in sorted(labels, key=_code_key)}
    var.missing_ranges = [
        MissingRange(float(c), float(c)) if var.numeric and _code_key(c)[0] == 0 else MissingRange(c, c)
        for c in sorted(missing, key=_code_key)
    ]
    return var


# -- statistics ------------------------------------------------------------------------


def _number(g: Graph, bundle) -> float | None:
    stat = g.value(bundle, CDI.statistic)
    value = g.value(stat, CDI.content) if stat is not None else None
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _statistics(g: Graph, nodes: list, variables: list[Variable], rows: int | None):
    """The StatisticsCollection of each variable -> what qsv's two passes return."""
    from ..cdi.statistics import FREQUENCY, INVALID_CASES, PERCENTAGE, VALID_CASES, VALID_ONLY, StatisticsData
    from ..stats import KIND_CATEGORICAL, Category, CategoryStats, DatasetStats, SummaryStat, VariableStats

    by_iri = {str(n): v for n, v in zip(nodes, variables)}
    summaries: list[VariableStats] = []
    categories: list[CategoryStats] = []
    weight: Variable | None = None
    excludes = True
    for node, var in zip(nodes, variables):
        coll = g.value(node, CDIF.isDescribedBy_StatisticsCollection)
        if coll is None:
            continue
        w = g.value(coll, CDI.hasWeight)
        if w is not None and str(w) in by_iri:
            weight = by_iri[str(w)]
        stats: list[SummaryStat] = []
        counts = {VALID_CASES: 0.0, INVALID_CASES: 0.0}
        freq: dict[str, dict[str, float]] = {}
        for bundle in g.objects(coll, CDIF.has_Statistics):
            kind = _str(g, bundle, CDIF.typeOfStatistic)
            parts = list(g.objects(bundle, CDIF.has_CategoryStatistics))
            if parts:  # frequency / percentage: one CategoryStatistics per category
                for part in parts:
                    code = _str(g, g.value(part, CDI["for"]), CDIF.name)
                    value = _number(g, part)
                    if code and value is not None:
                        freq.setdefault(code, {})[_str(g, part, CDIF.typeOfStatistic) or kind] = value
                continue
            value = _number(g, bundle)
            if value is None:
                continue
            if kind in counts:
                counts[kind] = value
            else:
                stats.append(SummaryStat(name=kind, value=_text(value)))
                if _str(g, g.value(bundle, CDI.statistic), CDI.computationBase) not in ("", VALID_ONLY):
                    excludes = False
        valid_n, missing_n = int(counts[VALID_CASES]), int(counts[INVALID_CASES])
        kind = KIND_CATEGORICAL if freq else "numeric" if var.numeric else "text"
        storage = var.storage_type.lower()
        summaries.append(VariableStats(
            name=var.name, kind=kind if valid_n else "empty", numeric=var.numeric,
            qsv_type="Integer" if "int" in storage else "Float" if var.numeric else "String",
            valid_n=valid_n, missing_n=missing_n,
            cardinality=len(freq) if freq else None, has_categories=bool(freq),
            stats=sorted(stats, key=lambda s: s.name)))
        if freq:
            total = sum(f.get(FREQUENCY, 0.0) for f in freq.values())
            ranked = sorted(freq, key=lambda c: -freq[c].get(FREQUENCY, 0.0))
            cats = [Category(code=c, label=var.value_labels.get(c), count=freq[c].get(FREQUENCY, 0.0),
                             percent=freq[c].get(PERCENTAGE, 100.0 * freq[c].get(FREQUENCY, 0.0) / total if total else 0.0),
                             rank=ranked.index(c) + 1, sentinel=var.is_missing_code(c))
                    for c in sorted(freq, key=_code_key)]
            sentinel_n = sum(x.count for x in cats if x.sentinel)
            categories.append(CategoryStats(
                name=var.name, label=var.label, total_rows=rows or valid_n + missing_n, valid_n=valid_n,
                valid_n_substantive=int(valid_n - sentinel_n), missing_n=missing_n, cardinality=len(cats),
                all_unique=False, truncated=False, other_count=0.0,
                weight=None, categories=cats))
    if not summaries:
        return None
    if weight is not None:
        for c in categories:
            c.weight = weight.name
        if all(s.name != weight.name for s in summaries):
            # qsv leaves the weight column out of a weighted run: it is there, without statistics.
            summaries.append(VariableStats(name=weight.name, kind="numeric", numeric=True, qsv_type="Float",
                                           valid_n=0, missing_n=0, is_weight=True))
    summary = DatasetStats(total_rows=rows or 0, weight=weight.name if weight else None, weight_candidates=[],
                           excludes_sentinels=excludes, degraded=False, elapsed_ms=0, variables=summaries)
    return StatisticsData(summary=summary, categories=categories, weighted=weight is not None,
                          weight=weight.name if weight else None)


def document_to_meta(g: Graph, doc_uuid: str, graph_iri: str) -> DatasetMeta:
    """One saved CDIF document -> a metadata-only workspace (no rows; see the module notes)."""
    ds = _dataset_node(g)
    dist = g.value(ds, SCHEMA.distribution)

    # Variables in file order: the physical mappings carry the column index.
    mapping_of = {}
    order = {}
    for m in g.objects(dist, CDIF.hasPhysicalMapping) if dist is not None else ():
        var = g.value(m, CDIF.formats_InstanceVariable)
        if var is not None:
            mapping_of[var] = m
            order[var] = _int(g, m, CDIF["index"])
    nodes = sorted(g.objects(ds, SCHEMA.variableMeasured),
                   key=lambda v: (order.get(v) if order.get(v) is not None else 1_000_000, _str(g, v, SCHEMA.name)))
    variables = [_variable(g, v, mapping_of.get(v)) for v in nodes]

    roles = Roles()
    for node, var in zip(nodes, variables):
        role = _ROLES.get(_str(g, node, CDIF.role))
        if role:
            getattr(roles, role).append(var.name)

    datafile = _str(g, dist, SCHEMA.name) if dist is not None else ""
    datafile = datafile or f"{_str(g, ds, SCHEMA.name) or doc_uuid}.csv"
    rows = None
    for prop in g.objects(dist, SCHEMA.additionalProperty) if dist is not None else ():
        if _str(g, prop, SCHEMA.name) == "countRows":
            rows = _int(g, prop, SCHEMA.value)
    checksum = g.value(dist, SPDX.checksum) if dist is not None else None
    size = _int(g, dist, SCHEMA.contentSize) if dist is not None else None
    meta = DatasetMeta(
        variables=variables,
        number_rows=0,
        datafile=datafile,
        file_format=_FILE_FORMATS.get(Path(datafile).suffix.lower(), "csv"),
        delimiter=(_str(g, dist, CDI.delimiter) or None) if dist is not None else None,
        roles=roles,
        info=_info(g, ds, dist),
        file_size=size,
        file_md5=_str(g, checksum, SPDX.checksumValue) or None if checksum is not None else None,
        doc_uuid=doc_uuid,
        opened_from=graph_iri,
        source_rows=rows,
    )
    # No data, so nothing was lost on the way in (the editor warns about empty user-missing cells otherwise).
    meta.sentinels_in_data = True
    saved = _statistics(g, nodes, variables, rows)
    if saved is not None:
        from ..saved_statistics import to_dict
        meta.saved_statistics = to_dict(saved, meta)
    return meta
