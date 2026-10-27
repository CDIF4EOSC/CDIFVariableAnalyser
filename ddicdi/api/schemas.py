"""Pydantic request/response models."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from typing import Any

from ..cdi.statistics import STATISTIC_NAMES
from ..models import DatasetInfo, DatasetMeta, Variable
from ..stats import CategoryStats, DatasetStats, VariableStats
from ..roles import default_roles, roles_to_assignments

class MissingRangeOut(BaseModel):
    lo: str
    hi: str


class ConceptOut(BaseModel):
    uri: str
    pref_label: str = ""


class VariableOut(BaseModel):
    name: str
    label: str | None
    format: str
    type: str
    measure: str
    numeric: bool
    value_labels: dict[str, str]
    missing: list[MissingRangeOut]
    default_role: str
    unit_of_measure: str | None = None
    concepts: list[ConceptOut] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list, description="Variable functions, e.g. Weight, UnitIdentifier")

    @classmethod
    def from_variable(cls, v: Variable, role: str) -> "VariableOut":
        return cls(
            name=v.name,
            label=v.label,
            format=v.format,
            type=v.storage_type,
            measure=v.measure,
            numeric=v.numeric,
            value_labels=v.value_labels,
            missing=[MissingRangeOut(**r.to_dict()) for r in v.missing_ranges],
            default_role=role,
            unit_of_measure=v.unit_of_measure,
            concepts=[ConceptOut(uri=c.uri, pref_label=c.pref_label) for c in v.concepts],
            functions=list(v.functions),
        )


# A date as ISO 8601 allows it in a citation: a year, a month or a day.
_ISO_DATE = r"^(\d{4}(-\d{2}(-\d{2})?)?)?$"


class AgentIO(BaseModel):
    name: str
    kind: Literal["person", "organization"] = "person"
    identifier: str = Field("", description="ORCID for a person, ROR for an organisation (bare or as a URL)")
    affiliation: str = ""
    affiliation_id: str = Field("", description="ROR of the affiliation")
    email: str = ""


class DatasetInfoIO(BaseModel):
    """Dataset-level description: what the CDIF discovery profile asks for beyond the variables."""

    title: str = ""
    description: str = ""
    identifier: str = Field("", description="DOI, handle or URL of the dataset")
    url: str = Field("", description="landing page")
    content_url: str = Field("", description="download URL of the data file")
    record_id: str = Field("", description="IRI of the metadata record, the CDIF document's @id")
    version: str = ""
    license: str = Field("", description="licence URI, e.g. https://creativecommons.org/licenses/by/4.0/")
    language: str = ""
    keywords: list[str] = Field(default_factory=list)
    date_published: str = Field("", pattern=_ISO_DATE)
    date_modified: str = Field("", pattern=_ISO_DATE)
    creators: list[AgentIO] = Field(default_factory=list)
    publisher: AgentIO | None = None

    @classmethod
    def from_info(cls, info: DatasetInfo) -> "DatasetInfoIO":
        return cls.model_validate(asdict(info))

    def to_info(self) -> DatasetInfo:
        return DatasetInfo.from_dict(self.model_dump())


class FileInfo(BaseModel):
    file_id: str
    filename: str
    file_format: str
    number_rows: int
    number_variables: int
    encoding: str | None
    file_label: str | None
    delimiter: str | None
    sentinels_in_data: bool = Field(
        False, description="User-missing codes are in the cells, not written as empty cells."
    )
    variables: list[VariableOut]
    preview: list[dict[str, str]] = Field(default_factory=list)
    info: DatasetInfoIO = Field(default_factory=DatasetInfoIO)
    file_size: int | None = Field(None, description="size of the uploaded file in bytes")
    file_md5: str | None = Field(None, description="MD5 checksum of the uploaded file")

    @classmethod
    def from_meta(cls, file_id: str, meta: DatasetMeta, preview: list[dict[str, str]]) -> "FileInfo":
        roles = {**default_roles(meta), **roles_to_assignments(meta.roles)}
        return cls(
            file_id=file_id,
            filename=meta.datafile,
            file_format=meta.file_format,
            number_rows=meta.number_rows,
            number_variables=len(meta.variables),
            encoding=meta.encoding,
            file_label=meta.file_label,
            delimiter=meta.delimiter,
            sentinels_in_data=meta.sentinels_in_data,
            variables=[VariableOut.from_variable(v, roles[v.name]) for v in meta.variables],
            preview=preview,
            info=DatasetInfoIO.from_info(meta.info),
            file_size=meta.file_size,
            file_md5=meta.file_md5,
        )


class StatisticsOptions(BaseModel):
    """The statistics half of a generate or output request."""

    include_statistics: bool = Field(
        False, description="Emit StatisticsCollection / Statistics / CategoryStatistics / Category / Notation elements (two qsv passes)"
    )
    statistics_weight: str | None = Field(
        None, description='Weight variable for the statistics, or "auto" for the first Weight-function one'
    )
    statistics_include: list[str] | None = Field(
        None,
        description=(
            "Which statistics to emit: DDI-CDI SummaryStatisticType terms plus validCases, "
            "invalidCases, frequency and percentage. Omitted or null = all of them; a selection "
            "without frequency or percentage also skips the qsv frequency pass."
        ),
    )

    @field_validator("statistics_include")
    @classmethod
    def _known_statistics(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        unknown = [name for name in value if name not in STATISTIC_NAMES]
        if unknown:
            raise ValueError(f"Unknown statistics {', '.join(unknown)}; expected one of {', '.join(STATISTIC_NAMES)}")
        return list(dict.fromkeys(value))


class GenerateRequest(StatisticsOptions):
    roles: dict[str, str] = Field(
        default_factory=dict,
        description='Variable -> comma separated roles, e.g. {"idno": "identifier", "cntry": "measure,attribute"}',
    )
    max_rows: int = Field(5, ge=0, description="Rows of data to include; 0 = metadata only")
    process_all_rows: bool = False


class OutputRequest(StatisticsOptions):
    """Regenerate the document for the editor preview (roles come from the stored metadata)."""

    max_rows: int = Field(5, ge=0)
    process_all_rows: bool = False


class RolesIn(BaseModel):
    roles: dict[str, str] = Field(default_factory=dict)


class VariablePatchIn(BaseModel):
    label: str | None = None
    format: str | None = None
    type: str | None = Field(None, description="storage type: double, string, int32 ...")
    measure: str | None = None
    value_labels: dict[str, str] | None = None
    missing: list[dict[str, Any]] | None = Field(None, description='[{"lo": 77, "hi": 77}, ...]')
    role: str | None = None
    new_name: str | None = None
    unit_of_measure: str | None = Field(None, description="EU measurement-unit URI; empty string clears")
    concepts: list[dict[str, Any]] | None = Field(None, description='[{"uri": ..., "pref_label": ...}]; [] clears')
    functions: list[str] | None = Field(None, description='["Weight", "UnitIdentifier", ...]; [] clears')


class NewVariableIn(BaseModel):
    name: str
    label: str | None = None
    format: str = ""
    type: str = "string"
    measure: str = "nominal"
    value_labels: dict[str, str] = Field(default_factory=dict)
    missing: list[dict[str, Any]] = Field(default_factory=list)
    role: str = "measure"
    fill: Literal["empty", "constant", "copy"] = "empty"
    fill_value: str = ""
    position: int | None = None
    unit_of_measure: str | None = None
    concepts: list[dict[str, Any]] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)


class CellsIn(BaseModel):
    values: dict[str, str | None]


class HealthOut(BaseModel):
    status: str
    version: str
    service: str
    qsv: str | None = None


# -- statistics ------------------------------------------------------------------------


class SummaryStatOut(BaseModel):
    """One statistic, named with its DDI-CDI ``SummaryStatisticType`` term."""

    name: str
    value: str


class VariableStatsOut(BaseModel):
    name: str
    label: str | None = None
    kind: Literal["numeric", "categorical", "text", "empty"]
    numeric: bool = Field(description="Storage type is numeric; independent of ``kind``")
    qsv_type: str
    valid_n: int
    missing_n: int
    cardinality: int | None = None
    cardinality_capped: bool = False
    has_categories: bool = False
    is_weight: bool = False
    sentinel_codes: list[str] = Field(default_factory=list)
    stats: list[SummaryStatOut] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, v: "VariableStats", label: str | None) -> "VariableStatsOut":
        return cls(
            name=v.name,
            label=label,
            kind=v.kind,  # type: ignore[arg-type]
            numeric=v.numeric,
            qsv_type=v.qsv_type,
            valid_n=v.valid_n,
            missing_n=v.missing_n,
            cardinality=v.cardinality,
            cardinality_capped=v.cardinality_capped,
            has_categories=v.has_categories,
            is_weight=v.is_weight,
            sentinel_codes=list(v.sentinel_codes),
            stats=[SummaryStatOut(name=s.name, value=s.value) for s in v.stats],
        )


class StatisticsOut(BaseModel):
    """Summary statistics for every variable. Not (yet) part of the DDI-CDI output."""

    file_id: str
    total_rows: int
    weight: str | None = None
    weight_candidates: list[str] = Field(default_factory=list)
    excludes_sentinels: bool = Field(
        description="True when user-missing codes are already out of the data (readstat imports)"
    )
    degraded: bool = Field(description="True when --everything was skipped because the file is large")
    elapsed_ms: int = 0
    variables: list[VariableStatsOut] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, file_id: str, ds: "DatasetStats", meta: DatasetMeta) -> "StatisticsOut":
        labels = {v.name: v.label for v in meta.variables}
        return cls(
            file_id=file_id,
            total_rows=ds.total_rows,
            weight=ds.weight,
            weight_candidates=list(ds.weight_candidates),
            excludes_sentinels=ds.excludes_sentinels,
            degraded=ds.degraded,
            elapsed_ms=ds.elapsed_ms,
            variables=[VariableStatsOut.from_domain(v, labels.get(v.name)) for v in ds.variables],
        )


class CategoryOut(BaseModel):
    code: str
    label: str | None = None
    count: float = Field(description="Float because weighted counts are fractional")
    percent: float
    rank: int
    sentinel: bool = False


class CategoryStatsOut(BaseModel):
    name: str
    label: str | None = None
    total_rows: int
    valid_n: int
    valid_n_substantive: int = Field(description="valid_n minus the declared missing codes still in the data")
    missing_n: int
    cardinality: int | None = None
    all_unique: bool = False
    truncated: bool = False
    other_count: float = 0.0
    weight: str | None = None
    categories: list[CategoryOut] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, c: "CategoryStats") -> "CategoryStatsOut":
        return cls(
            name=c.name,
            label=c.label,
            total_rows=c.total_rows,
            valid_n=c.valid_n,
            valid_n_substantive=c.valid_n_substantive,
            missing_n=c.missing_n,
            cardinality=c.cardinality,
            all_unique=c.all_unique,
            truncated=c.truncated,
            other_count=c.other_count,
            weight=c.weight,
            categories=[
                CategoryOut(
                    code=x.code, label=x.label, count=x.count,
                    percent=x.percent, rank=x.rank, sentinel=x.sentinel,
                )
                for x in c.categories
            ],
        )


# -- AI enrichment ---------------------------------------------------------------------


EnrichKind = Literal["unit", "concept", "role", "function", "measure"]


class EnrichIn(BaseModel):
    variables: list[str] | None = Field(None, description="Variable names; omit for all")
    kinds: list[EnrichKind] = Field(default_factory=lambda: ["unit", "concept", "role", "function", "measure"])


class EnrichSuggestion(BaseModel):
    name: str
    unit_of_measure: str | None = None
    concepts: list[ConceptOut] | None = None
    role: str | None = Field(None, description="Comma-joined DDI-CDI role(s): measure, identifier, attribute")
    functions: list[str] | None = Field(None, description="Variable functions, e.g. Weight; [] = none applies")
    measure: str | None = Field(None, description="Level of measurement: nominal, ordinal or scale")


class EnrichErrorOut(BaseModel):
    name: str | None
    kind: str
    message: str


class EnrichOut(BaseModel):
    """Suggestions only; nothing is written until the client PATCHes the variable."""

    suggestions: list[EnrichSuggestion]
    errors: list[EnrichErrorOut]
