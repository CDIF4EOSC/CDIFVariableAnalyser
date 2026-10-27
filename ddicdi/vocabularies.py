"""Controlled vocabularies for the dataset description.

Contributor roles are the DataCite ``contributorType`` values.
"""

from __future__ import annotations

from typing import NamedTuple


class Term(NamedTuple):
    code: str
    label: str
    uri: str


CONTRIBUTOR_ROLE_SET = "https://schema.datacite.org/meta/kernel-4/"
# No per-term URI: a role is named by its code in the DataCite schema.
CONTRIBUTOR_ROLES = (
    Term('ContactPerson', 'Contact person', ""),
    Term('DataCollector', 'Data collector', ""),
    Term('DataCurator', 'Data curator', ""),
    Term('DataManager', 'Data manager', ""),
    Term('Distributor', 'Distributor', ""),
    Term('Editor', 'Editor', ""),
    Term('HostingInstitution', 'Hosting institution', ""),
    Term('Producer', 'Producer', ""),
    Term('ProjectLeader', 'Project leader', ""),
    Term('ProjectManager', 'Project manager', ""),
    Term('ProjectMember', 'Project member', ""),
    Term('RegistrationAgency', 'Registration agency', ""),
    Term('RegistrationAuthority', 'Registration authority', ""),
    Term('RelatedPerson', 'Related person', ""),
    Term('Researcher', 'Researcher', ""),
    Term('ResearchGroup', 'Research group', ""),
    Term('RightsHolder', 'Rights holder', ""),
    Term('Sponsor', 'Sponsor', ""),
    Term('Supervisor', 'Supervisor', ""),
    Term('Translator', 'Translator', ""),
    Term('WorkPackageLeader', 'Work package leader', ""),
    Term('Other', 'Other', ""),
)


def find(terms: tuple[Term, ...], code: str) -> Term | None:
    return next((t for t in terms if t.code == code), None)


def as_json() -> dict[str, list[dict[str, str]]]:
    """The vocabularies for the editor's dropdowns."""
    return {
        "contributor_role": [t._asdict() for t in CONTRIBUTOR_ROLES],
    }

