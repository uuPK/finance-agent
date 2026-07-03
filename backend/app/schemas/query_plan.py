from typing import Any, Literal

from pydantic import BaseModel, Field


PlanStatus = Literal["draft", "ready", "needs_clarification", "invalid"]
QueryIntent = Literal[
    "customer_segmentation",
    "metric_query",
    "ranking_query",
    "trend_analysis",
    "detail_lookup",
    "marketing_effect_analysis",
    "metadata_question",
    "unclear",
]
ReferenceType = Literal["table", "column", "metric", "business_term", "join_path", "example"]
EntityType = Literal["customer", "manager", "product", "campaign", "organization", "unknown"]
AggregationType = Literal[
    "sum", "count", "count_distinct", "avg", "min", "max", "latest", "ratio", "custom"
]
DimensionRole = Literal["group_by", "display", "partition", "drilldown"]
FilterOperator = Literal[
    "=",
    "!=",
    ">",
    ">=",
    "<",
    "<=",
    "in",
    "not_in",
    "between",
    "like",
    "is_null",
    "is_not_null",
    "exists",
    "not_exists",
]
FilterSource = Literal["user", "business_term", "metric_definition", "default", "critic_repair"]
TimeGranularity = Literal["day", "week", "month", "quarter", "year", "none"]
SortDirection = Literal["asc", "desc"]
OutputFormat = Literal["table", "summary", "chart", "sql_only"]


class MetadataReference(BaseModel):
    ref_type: ReferenceType
    ref_id: str | None = None
    code: str | None = None
    name: str


class BusinessEntity(BaseModel):
    name: str
    entity_type: EntityType = "unknown"
    metadata_ref: MetadataReference | None = None
    is_resolved: bool = False


class TimeRange(BaseModel):
    label: str | None = None
    start: str | None = None
    end: str | None = None
    relative: str | None = None
    granularity: TimeGranularity = "none"
    anchor_date: str | None = None
    is_resolved: bool = False


class QueryValue(BaseModel):
    raw: Any
    normalized: Any | None = None
    value_type: Literal[
        "string", "number", "date", "datetime", "boolean", "list", "range", "relative_time"
    ] = "string"


class QueryFilter(BaseModel):
    term: str
    operator: FilterOperator
    value: QueryValue
    field_code: str | None = None
    metric_code: str | None = None
    source: FilterSource = "user"
    metadata_ref: MetadataReference | None = None
    is_resolved: bool = False
    requires_clarification: bool = False


class QueryMetric(BaseModel):
    name: str
    metric_code: str | None = None
    definition_id: str | None = None
    aggregation: AggregationType | None = None
    alias: str | None = None
    time_window: TimeRange | None = None
    filters: list[QueryFilter] = Field(default_factory=list)
    metadata_ref: MetadataReference | None = None
    is_resolved: bool = False
    requires_clarification: bool = False


class QueryDimension(BaseModel):
    name: str
    dimension_code: str | None = None
    role: DimensionRole = "display"
    alias: str | None = None
    metadata_ref: MetadataReference | None = None
    is_resolved: bool = False


class QueryGrain(BaseModel):
    level: str
    keys: list[str] = Field(default_factory=list)
    description: str | None = None
    is_resolved: bool = False


class DataRequirement(BaseModel):
    domains: list[str] = Field(default_factory=list)
    candidate_tables: list[str] = Field(default_factory=list)
    required_join_paths: list[str] = Field(default_factory=list)
    required_metadata_refs: list[MetadataReference] = Field(default_factory=list)


class QuerySort(BaseModel):
    term: str
    direction: SortDirection = "desc"
    metric_code: str | None = None
    field_code: str | None = None


class QueryOutput(BaseModel):
    format: OutputFormat = "table"
    columns: list[str] = Field(default_factory=list)
    limit: int = Field(default=100, ge=1, le=10000)
    include_sql: bool = True
    include_explanation: bool = True


class SafetyRequirement(BaseModel):
    readonly: bool = True
    max_rows: int = Field(default=1000, ge=1)
    allow_sensitive_fields: bool = False
    require_limit: bool = True
    require_metric_definition: bool = True


class ClarificationQuestion(BaseModel):
    field: str
    question: str
    reason: str
    options: list[str] = Field(default_factory=list)


class PlanAssumption(BaseModel):
    field: str
    value: Any
    reason: str
    source: FilterSource = "default"


class QueryPlan(BaseModel):
    version: str = "1.0"
    plan_status: PlanStatus = "draft"
    intent: QueryIntent = "unclear"
    scenario: str = "customer_marketing"
    question: str | None = None
    subject: BusinessEntity | None = None
    entities: list[BusinessEntity] = Field(default_factory=list)
    metrics: list[QueryMetric] = Field(default_factory=list)
    dimensions: list[QueryDimension] = Field(default_factory=list)
    filters: list[QueryFilter] = Field(default_factory=list)
    time_range: TimeRange | None = None
    grain: QueryGrain | None = None
    data_requirements: DataRequirement = Field(default_factory=DataRequirement)
    order_by: list[QuerySort] = Field(default_factory=list)
    output: QueryOutput = Field(default_factory=QueryOutput)
    safety: SafetyRequirement = Field(default_factory=SafetyRequirement)
    clarifications: list[ClarificationQuestion] = Field(default_factory=list)
    assumptions: list[PlanAssumption] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
