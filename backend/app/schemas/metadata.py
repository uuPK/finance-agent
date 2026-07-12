from typing import Any

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


class MetadataBusinessTerm(BaseModel):
    term: str
    definition: str
    synonyms: list[str] = Field(default_factory=list)
    default_plan_fragment: dict[str, Any] = Field(default_factory=dict)
    clarification_required: bool = False


class MetadataJoin(BaseModel):
    left_schema: str
    left_table: str
    left_column: str
    right_schema: str
    right_table: str
    right_column: str
    relationship_type: str
    description: str


class MetadataQuestionExample(BaseModel):
    question: str
    difficulty: str
    scenario: str
    expected_query_plan: dict[str, Any] = Field(default_factory=dict)
    expected_sql: str | None = None
    tags: list[str] = Field(default_factory=list)
