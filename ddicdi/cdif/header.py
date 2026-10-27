"""The editor's dataset description as a DDI-CDI JSON-LD header for the CDIF converter.

The converter reads a header in the shape of the CODATA DDI-CDI export (``@id`` and
``dct:`` terms at the top level, beside ``DDICDIModels``) and copies the schema.org
discovery terms it finds there. Only filled-in fields are written.
"""

from __future__ import annotations

import re

from ..models import Agent, DatasetInfo

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


def dataset_header(info: DatasetInfo) -> dict:
    """Header entries for ``convert_document``; empty when nothing was entered."""
    header: dict = {}
    if info.record_id:
        header["@id"] = info.record_id
    for key, val in (
        ("dct:title", info.title),
        ("dct:description", info.description),
        ("dct:identifier", info.identifier),
        ("dct:license", {"@id": info.license} if info.license else None),
        ("dct:language", info.language),
        ("schema:url", info.url),
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
    return header
