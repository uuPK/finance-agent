from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TableMetadata(Base):
    __tablename__ = "table_metadata"
    __table_args__ = (
        UniqueConstraint("schema_name", "table_name", name="uq_table_metadata"),
        {"schema": "metadata"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    schema_name: Mapped[str] = mapped_column(String(64), default="mart")
    table_name: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    domain: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    grain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    refresh_frequency: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ColumnMetadata(Base):
    __tablename__ = "column_metadata"
    __table_args__ = (
        UniqueConstraint("schema_name", "table_name", "column_name", name="uq_column_metadata"),
        {"schema": "metadata"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    schema_name: Mapped[str] = mapped_column(String(64), default="mart")
    table_name: Mapped[str] = mapped_column(String(128), index=True)
    column_name: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    data_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    semantic_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_dimension: Mapped[bool] = mapped_column(Boolean, default=False)
    is_metric_source: Mapped[bool] = mapped_column(Boolean, default=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MetricMetadata(Base):
    __tablename__ = "metric_metadata"
    __table_args__ = {"schema": "metadata"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    metric_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    metric_name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    formula: Mapped[str] = mapped_column(Text)
    default_aggregation: Mapped[str] = mapped_column(String(64), default="")
    grain: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_schema: Mapped[str] = mapped_column(String(64), default="mart")
    source_tables: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_filters: Mapped[list[dict]] = mapped_column(JSON, default=list)
    owner: Mapped[str] = mapped_column(String(64), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BusinessTerm(Base):
    __tablename__ = "business_terms"
    __table_args__ = {"schema": "metadata"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    term: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    definition: Mapped[str] = mapped_column(Text)
    synonyms: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_plan_fragment: Mapped[dict] = mapped_column(JSON, default=dict)
    clarification_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class JoinRelationship(Base):
    __tablename__ = "join_relationships"
    __table_args__ = {"schema": "metadata"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    left_schema: Mapped[str] = mapped_column(String(64), default="mart")
    left_table: Mapped[str] = mapped_column(String(128), index=True)
    left_column: Mapped[str] = mapped_column(String(128))
    right_schema: Mapped[str] = mapped_column(String(64), default="mart")
    right_table: Mapped[str] = mapped_column(String(128), index=True)
    right_column: Mapped[str] = mapped_column(String(128))
    relationship_type: Mapped[str] = mapped_column(String(32), default="many_to_one")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class QuestionExample(Base):
    __tablename__ = "question_examples"
    __table_args__ = {"schema": "metadata"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(32), index=True)
    scenario: Mapped[str] = mapped_column(String(64), default="customer_marketing")
    expected_query_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_sql: Mapped[str] = mapped_column(Text, default="")
    expected_result: Mapped[dict] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RuleConstraint(Base):
    __tablename__ = "rule_constraints"
    __table_args__ = {"schema": "metadata"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rule_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rule_name: Mapped[str] = mapped_column(String(128))
    rule_type: Mapped[str] = mapped_column(String(64), index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    severity: Mapped[str] = mapped_column(String(16), default="error")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
