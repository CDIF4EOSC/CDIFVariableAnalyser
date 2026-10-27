"""The editor's dataset description as a DDI-CDI JSON-LD header for the CDIF converter.

The converter reads a header in the shape of the CODATA DDI-CDI export (``@id`` and
``dct:`` terms at the top level, beside ``DDICDIModels``) and copies the schema.org
discovery terms it finds there. Only filled-in fields are written.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .. import vocabularies as cv
from ..models import Agent, DatasetMeta, Grant, Methodology

_ORCID_RE = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")  # 0000-0002-1825-0097
_ROR_RE = re.compile(r"^0[a-z0-9]{6}\d{2}$")  # 05xg72x27


def _iri(identifier: str) -> str | None:
    """An ORCID or ROR, bare or as a URL, or any other URL -> its IRI; None otherwise."""
    identifier = identifier.strip()
    if identifier.startswith(("http://", "https://")):
        return identifier
    if _ORCID_RE.match(identifier):
        return "https://orcid.org/" + identifier
    if _ROR_RE.match(identifier):
        return "https://ror.org/" + identifier
    return None


def _identify(node: dict, identifier: str) -> None:
    # As schema:identifier, not @id: the same organisation entered twice (an affiliation
    # and the publisher) under two spellings would otherwise merge into one node with
    # two names.
    if identifier.strip():
        node["schema:identifier"] = _iri(identifier) or identifier.strip()


def agent_node(agent: Agent) -> dict:
    """A creator or publisher -> schema:Person / schema:Organization."""
    node: dict = {
        "@type": ["schema:Organization" if agent.kind == "organization" else "schema:Person"],
        "schema:name": agent.name,
    }
    _identify(node, agent.identifier)
    if agent.affiliation and agent.kind != "organization":
        org: dict = {"@type": ["schema:Organization"], "schema:name": agent.affiliation}
        _identify(org, agent.affiliation_id)
        node["schema:affiliation"] = org
    if agent.email:
        node["schema:contactPoint"] = {"@type": ["schema:ContactPoint"], "schema:email": agent.email}
    return node


def _term(terms: tuple[cv.Term, ...], term_set: str, code: str) -> dict | str:
    """A vocabulary code -> schema:DefinedTerm; an unknown code stays a plain string."""
    term = cv.find(terms, code)
    if term is None:
        return code
    node: dict = {"@type": ["schema:DefinedTerm"], "schema:name": term.label,
                  "schema:termCode": term.code, "schema:inDefinedTermSet": term_set}
    if term.uri:
        node["schema:identifier"] = term.uri
    return node


def contributor_node(agent: Agent) -> dict:
    """A contributor with a role -> schema:Role around the person or organisation, as CDIF
    nests it; without a role, the agent itself."""
    if not agent.role:
        return agent_node(agent)
    return {
        "@type": ["schema:Role"],
        "schema:roleName": _term(cv.CONTRIBUTOR_ROLES, cv.CONTRIBUTOR_ROLE_SET, agent.role),
        "schema:contributor": agent_node(agent),
    }


def _interval(start: str, end: str) -> list:
    """A period -> an ISO 8601 interval string, plus a time:ProperInterval when both ends are
    full dates (time:inXSDDate takes an xsd:date)."""
    out: list = [f"{start or '..'}/{end or '..'}"]
    if len(start) == 10 and len(end) == 10:
        out.insert(0, {
            "@type": ["time:ProperInterval"],
            "time:hasBeginning": {"@type": ["time:Instant"], "time:inXSDDate": start},
            "time:hasEnd": {"@type": ["time:Instant"], "time:inXSDDate": end},
        })
    return out


def grant_node(grant: Grant) -> dict:
    node: dict = {"@type": ["schema:MonetaryGrant"]}
    if grant.title:
        node["schema:name"] = grant.title
    if grant.award:
        node["schema:identifier"] = {"@type": ["schema:PropertyValue"], "schema:propertyID": "Award number",
                                     "schema:value": grant.award}
    if grant.funder or grant.funder_id:
        funder: dict = {"@type": ["schema:Organization"], "schema:name": grant.funder or grant.funder_id}
        _identify(funder, grant.funder_id)
        node["schema:funder"] = funder
    return node


def activity_node(m: Methodology) -> dict:
    """The data collection -> a schema:Action / prov:Activity (CDIF provenance). The universe
    is what the action is carried out on (schema:object); the sampling procedure is its
    method (schema:actionProcess, a schema:HowTo)."""
    node: dict = {"@type": ["schema:Action", "prov:Activity"], "schema:name": "Data collection"}
    if m.description:
        node["schema:description"] = m.description
    if m.collection_start:
        node["schema:startTime"] = m.collection_start
    if m.collection_end:
        node["schema:endTime"] = m.collection_end
    if m.universe:
        node["schema:object"] = m.universe
    if m.instrument:
        node["prov:used"] = [{"@id": m.instrument} if _iri(m.instrument) else m.instrument]
    if m.sampling or m.sampling_description:
        term = cv.find(cv.SAMPLING_PROCEDURE, m.sampling)
        howto: dict = {"@type": ["schema:HowTo"],
                       "schema:name": term.label if term else (m.sampling or "Sampling procedure")}
        if m.sampling_description:
            howto["schema:description"] = m.sampling_description
        if m.sampling:
            howto["schema:additionalType"] = [_term(cv.SAMPLING_PROCEDURE, cv.SAMPLING_PROCEDURE_SET, m.sampling)]
        node["schema:actionProcess"] = howto
    return node


def dataset_header(meta: DatasetMeta) -> dict:
    """Header entries for ``convert_document``: the editor's dataset description and the
    size and checksum of the uploaded file. Only what is known is written."""
    info = meta.info
    header: dict = {}
    if meta.file_size is not None:
        header["schema:contentSize"] = meta.file_size
    if meta.file_md5:
        header["schema:checksum"] = {"schema:algorithm": "md5", "schema:checksumValue": meta.file_md5}
    if info.record_id:
        header["@id"] = info.record_id
    for key, val in (
        ("dct:title", info.title),
        ("dct:description", info.description),
        ("dct:identifier", info.identifier),
        ("dct:license", {"@id": info.license} if info.license else None),
        ("dct:language", info.language),
        ("schema:url", info.url),
        ("schema:contentUrl", info.content_url),
        ("schema:version", info.version),
        ("schema:datePublished", info.date_published),
        ("schema:dateModified", info.date_modified),
    ):
        if val:
            header[key] = val
    keywords = [k.strip() for k in info.keywords if k.strip()]
    if keywords:
        header["schema:keywords"] = keywords
    creators = [agent_node(a) for a in info.creators if a.name.strip()]
    if creators:
        # The order of the authors matters for a citation.
        header["schema:creator"] = {"@list": creators}
    if info.publisher and info.publisher.name.strip():
        header["schema:publisher"] = agent_node(info.publisher)
    contributors = [contributor_node(a) for a in info.contributors if a.name.strip()]
    if contributors:
        header["schema:contributor"] = contributors
    if info.temporal_start or info.temporal_end:
        header["schema:temporalCoverage"] = _interval(info.temporal_start, info.temporal_end)
    places = [p.strip() for p in info.spatial if p.strip()]
    if places:
        header["schema:spatialCoverage"] = [{"@type": ["schema:Place"], "schema:name": p} for p in places]
    grants = [grant_node(g) for g in info.funding if g.funder or g.funder_id or g.award or g.title]
    if grants:
        header["schema:funding"] = grants
    m = info.methodology
    if m.modes:
        header["schema:measurementTechnique"] = [
            _term(cv.MODE_OF_COLLECTION, cv.MODE_OF_COLLECTION_SET, code) for code in m.modes]
    if not replace(m, modes=[]).is_empty():  # the modes alone are measurementTechnique
        header["prov:wasGeneratedBy"] = [activity_node(m)]
    return header
