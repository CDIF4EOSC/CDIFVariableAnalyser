"""Engine independent description of an imported dataset.

The attribute names mirror what the DDI-CDI generator needs and roughly what
pyreadstat exposed in the original app (``column_names``, ``missing_ranges``,
``variable_value_labels`` ...) so the JSON-LD port stays recognisable.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Iterator

_INTEGRAL_RE = re.compile(r"^-?\d+\.0+$")
# SPSS ``F8.2`` / ``A20`` / ``DATETIME23.2``, Stata ``%9.0g`` / ``%12s``, SAS ``BEST12.`` / ``$20.`` / ``8.2``
_FORMAT_RE = re.compile(r"^([^\d]*?)(\d+)(?:\.(\d*))?([a-zA-Z]*)$")


def normalize_number(text: str) -> str:
    """``11.0`` -> ``11``; everything else unchanged."""
    if _INTEGRAL_RE.match(text):
        return text.split(".", 1)[0]
    return text


def format_number(value: float) -> str:
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


def parse_format(fmt: str) -> tuple[int | None, int | None]:
    """``(width, decimals)`` of a native print format; ``None`` for a part the format lacks.

    Same split as the Studio's format editor: ``F8.2`` -> (8, 2), ``A20`` -> (20, None),
    ``%9.0g`` -> (9, 0), ``BEST12.`` -> (12, None), ``%tdCCYY`` -> (None, None).
    """
    m = _FORMAT_RE.match((fmt or "").strip())
    if not m:
        return None, None
    decimals = int(m.group(3)) if m.group(3) else None
    return int(m.group(2)), decimals


@dataclass
class MissingRange:
    """A declared user-missing value (``lo == hi``) or range."""

    lo: float | str
    hi: float | str

    @property
    def numeric(self) -> bool:
        return isinstance(self.lo, (int, float))

    def contains(self, cell: str) -> bool:
        if cell == "":
            return False
        if self.numeric:
            try:
                value = float(cell)
            except ValueError:
                return False
            return float(self.lo) <= value <= float(self.hi)
        return str(self.lo) <= cell <= str(self.hi)

    def to_dict(self) -> dict[str, str]:
        if self.numeric:
            return {"lo": format_number(float(self.lo)), "hi": format_number(float(self.hi))}
        return {"lo": str(self.lo), "hi": str(self.hi)}


@dataclass
class Concept:
    """A concept the variable measures, e.g. an ELSST thesaurus entry."""

    uri: str
    pref_label: str = ""


@dataclass
class Variable:
    name: str
    label: str | None = None
    format: str = ""  # file native format, e.g. F2.0, A8, %9.0g
    storage_type: str = "string"  # readstat style: double, string, int8, float ...
    measure: str = "unknown"  # nominal | ordinal | scale | unknown
    numeric: bool = False
    value_labels: dict[str, str] = field(default_factory=dict)  # code -> label
    missing_ranges: list[MissingRange] = field(default_factory=list)
    unit_of_measure: str | None = None  # EU Publications Office measurement-unit URI
    concepts: list[Concept] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)  # e.g. Weight, UnitIdentifier; see functions.py

    @property
    def has_missing(self) -> bool:
        return bool(self.missing_ranges)

    @property
    def width(self) -> int | None:
        return parse_format(self.format)[0]

    @property
    def decimals(self) -> int | None:
        return parse_format(self.format)[1]

    def is_missing_code(self, code: str) -> bool:
        return any(r.contains(code) for r in self.missing_ranges)

    def normalize(self, cell: str) -> str:
        return normalize_number(cell) if self.numeric else cell

    def substantive_codes(self) -> list[str]:
        return [c for c in self.value_labels if not self.is_missing_code(c)]

    def sentinel_codes(self) -> list[str]:
        return [c for c in self.value_labels if self.is_missing_code(c)]


@dataclass
class Roles:
    measure: list[str] = field(default_factory=list)
    identifier: list[str] = field(default_factory=list)
    attribute: list[str] = field(default_factory=list)


@dataclass
class Agent:
    """A person or organisation credited for the dataset (creator or publisher)."""

    name: str
    kind: str = "person"  # person | organization
    identifier: str = ""  # ORCID for a person, ROR for an organisation
    affiliation: str = ""
    affiliation_id: str = ""  # ROR of the affiliation
    email: str = ""
    role: str = ""  # contributors only: a DataCite contributorType, e.g. DataCollector


@dataclass
class Grant:
    """Funding for the dataset: who paid, and the award."""

    funder: str = ""
    funder_id: str = ""  # ROR
    award: str = ""  # award number
    title: str = ""  # name of the grant or project


@dataclass
class DatasetInfo:
    """Dataset-level description entered in the editor: title, people, dates and the like.

    None of it is in the data file. The CDIF output needs it for its discovery profile;
    the DDI-CDI output does not carry it.
    """

    title: str = ""
    description: str = ""
    identifier: str = ""  # DOI, handle or URL of the dataset
    url: str = ""  # landing page
    content_url: str = ""  # where the data file itself can be downloaded
    record_id: str = ""  # IRI of the metadata record (the CDIF document's @id)
    version: str = ""
    license: str = ""  # licence URI
    language: str = ""
    keywords: list[str] = field(default_factory=list)
    date_published: str = ""  # ISO 8601
    date_modified: str = ""
    creators: list[Agent] = field(default_factory=list)
    publisher: Agent | None = None
    contributors: list[Agent] = field(default_factory=list)  # each with a role
    temporal_start: str = ""  # the period the data are about
    temporal_end: str = ""
    spatial: list[str] = field(default_factory=list)  # place names, e.g. countries
    funding: list[Grant] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetInfo":
        publisher = d.get("publisher")
        known = {f.name for f in fields(cls)}  # a stored workspace may carry dropped fields
        return cls(
            **{
                **{k: v for k, v in d.items() if k in known},
                "keywords": list(d.get("keywords", [])),
                "creators": [Agent(**a) for a in d.get("creators", [])],
                "publisher": Agent(**publisher) if publisher else None,
                "contributors": [Agent(**a) for a in d.get("contributors", [])],
                "spatial": list(d.get("spatial", [])),
                "funding": [Grant(**g) for g in d.get("funding", [])],
            }
        )


@dataclass
class DatasetMeta:
    variables: list[Variable]
    number_rows: int
    datafile: str  # original file name as uploaded
    file_format: str  # spss | stata | sas | csv | parquet
    delimiter: str | None = None
    encoding: str | None = None
    file_label: str | None = None
    roles: Roles = field(default_factory=Roles)
    # The declared missing codes are in data.csv (always for a CSV upload; for a readstat
    # import only when qsv kept them), rather than written as empty cells.
    sentinels_in_data: bool = False
    info: DatasetInfo = field(default_factory=DatasetInfo)
    # The uploaded file as it arrived, for the CDIF distribution.
    file_size: int | None = None
    file_md5: str | None = None

    # -- convenience ------------------------------------------------------------

    @property
    def column_names(self) -> list[str]:
        return [v.name for v in self.variables]

    def __iter__(self) -> Iterator[Variable]:
        return iter(self.variables)

    def var(self, name: str) -> Variable:
        for v in self.variables:
            if v.name == name:
                return v
        raise KeyError(name)

    @property
    def variables_with_missing(self) -> list[Variable]:
        return [v for v in self.variables if v.has_missing]

    # -- (de)serialisation --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for v in d["variables"]:
            v["missing_ranges"] = [
                {"lo": _json_num(r["lo"]), "hi": _json_num(r["hi"])} for r in v["missing_ranges"]
            ]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DatasetMeta":
        variables = []
        for v in d["variables"]:
            ranges = [MissingRange(_from_json_num(r["lo"]), _from_json_num(r["hi"])) for r in v["missing_ranges"]]
            concepts = [Concept(**c) for c in v.get("concepts", [])]
            variables.append(
                Variable(
                    **{
                        **v,
                        "missing_ranges": ranges,
                        "unit_of_measure": v.get("unit_of_measure"),
                        "concepts": concepts,
                        "functions": list(v.get("functions", [])),
                    }
                )
            )
        roles = Roles(**d.get("roles", {}))
        return cls(
            variables=variables,
            number_rows=d["number_rows"],
            datafile=d["datafile"],
            file_format=d["file_format"],
            delimiter=d.get("delimiter"),
            encoding=d.get("encoding"),
            file_label=d.get("file_label"),
            sentinels_in_data=d.get("sentinels_in_data", d["file_format"] in ("csv", "parquet")),
            roles=roles,
            info=DatasetInfo.from_dict(d.get("info", {})),
            file_size=d.get("file_size"),
            file_md5=d.get("file_md5"),
        )


def _json_num(v: float | str) -> float | str:
    if isinstance(v, float) and math.isinf(v):
        return "inf" if v > 0 else "-inf"
    return v


def _from_json_num(v: float | str) -> float | str:
    if v == "inf":
        return math.inf
    if v == "-inf":
        return -math.inf
    return v
