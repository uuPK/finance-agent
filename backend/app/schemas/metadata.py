from typing import Any, Literal

from pydantic import BaseModel, Field


class MetadataOverview(BaseModel):
    table_count: int = 0
    column_count: int = 0
    metric_count: int = 0
    term_count: int = 0
    join_count: int = 0
    example_count: int = 0


class MetadataTable(BaseModel):
    schema_name: str
    table_name: str
    display_name: str
    domain: str
    description: str
    grain: str | None = None
    refresh_frequency: str | None = None
    column_count: int = 0


class MetadataColumn(BaseModel):
    schema_name: str
    table_name: str
    column_name: str
    display_name: str
    data_type: str
    description: str
    semantic_type: str | None = None
    is_dimension: bool = False
    is_metric_source: bool = False
    is_sensitive: bool = False


class MetadataTableDetail(MetadataTable):
    columns: list[MetadataColumn] = Field(default_factory=list)


class MetadataMetric(BaseModel):
    metric_code: str
    metric_name: str
    description: str
    formula: str
    default_aggregation: str | None = None
    grain: str | None = None
    source_tables: list[str] = Field(default_factory=list)
    required_filters: list[dict[str, Any]] = Field(default_factory=list)
    owner: str = ""


class MetadataBusinessTerm(BaseModel):
    term: str
    definition: str
    synonyms: list[str] = Field(default_factory=list)
    default_plan_fragment: dict[str, Any] = Field(default_factory=dict)
    clarification_required: bool = False


class MetadataJoin(BaseModel):
    id: int
    left_schema: str
    left_table: str
    left_column: str
    right_schema: str
    right_table: str
    right_column: str
    relationship_type: str
    description: str


class MetadataQuestionExample(BaseModel):
    id: int
    question: str
    difficulty: str
    scenario: str
    expected_query_plan: dict[str, Any] = Field(default_factory=dict)
    expected_sql: str | None = None
    expected_result: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class MetadataRuleConstraint(BaseModel):
    rule_code: str
    rule_name: str
    rule_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    severity: str = "error"
    description: str = ""


class MetadataMetricInput(BaseModel):
    metric_code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    metric_name: str = Field(min_length=1, max_length=128)
    description: str = ""
    formula: str = Field(min_length=1)
    default_aggregation: str = ""
    grain: str | None = None
    source_tables: list[str] = Field(default_factory=list)
    required_filters: list[dict[str, Any]] = Field(default_factory=list)
    owner: str = "manual_catalog"


class MetadataBusinessTermInput(BaseModel):
    term: str = Field(min_length=1, max_length=128)
    definition: str = Field(min_length=1)
    synonyms: list[str] = Field(default_factory=list)
    default_plan_fragment: dict[str, Any] = Field(default_factory=dict)
    clarification_required: bool = False


class MetadataJoinInput(BaseModel):
    left_schema: str = Field(default="mart", min_length=1, max_length=64)
    left_table: str = Field(min_length=1, max_length=128)
    left_column: str = Field(min_length=1, max_length=128)
    right_schema: str = Field(default="mart", min_length=1, max_length=64)
    right_table: str = Field(min_length=1, max_length=128)
    right_column: str = Field(min_length=1, max_length=128)
    relationship_type: str = Field(default="many_to_one", min_length=1, max_length=32)
    description: str = ""


class MetadataQuestionExampleInput(BaseModel):
    question: str = Field(min_length=1)
    difficulty: str = Field(default="medium", min_length=1, max_length=32)
    scenario: str = Field(default="customer_marketing", min_length=1, max_length=64)
    expected_query_plan: dict[str, Any] = Field(default_factory=dict)
    expected_sql: str = ""
    expected_result: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class MetadataRuleConstraintInput(BaseModel):
    rule_code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    rule_name: str = Field(min_length=1, max_length=128)
    rule_type: str = Field(min_length=1, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    severity: str = Field(default="error", min_length=1, max_length=16)
    description: str = ""


MetadataChangeKind = Literal["metric", "term", "join", "example", "rule"]


class MetadataChangeInput(BaseModel):
    """A review-approved metadata change; actual payload validation is kind-specific."""

    action: Literal["create", "update"] = "create"
    kind: MetadataChangeKind
    payload: dict[str, Any] = Field(default_factory=dict)
