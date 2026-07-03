from sqlalchemy import Boolean, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TableMetadata(Base):
    __tablename__ = "table_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    table_name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    domain: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ColumnMetadata(Base):
    __tablename__ = "column_metadata"
    __table_args__ = (UniqueConstraint("table_name", "column_name", name="uq_table_column"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    table_name: Mapped[str] = mapped_column(String(128), index=True)
    column_name: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    data_type: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    is_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MetricMetadata(Base):
    __tablename__ = "metric_metadata"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    metric_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    metric_name: Mapped[str] = mapped_column(String(128), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    formula: Mapped[str] = mapped_column(Text)
    default_aggregation: Mapped[str] = mapped_column(String(64), default="")
    owner: Mapped[str] = mapped_column(String(64), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BusinessTerm(Base):
    __tablename__ = "business_terms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    term: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    definition: Mapped[str] = mapped_column(Text)
    synonyms: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_plan_fragment: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class JoinRelationship(Base):
    __tablename__ = "join_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    left_table: Mapped[str] = mapped_column(String(128), index=True)
    left_column: Mapped[str] = mapped_column(String(128))
    right_table: Mapped[str] = mapped_column(String(128), index=True)
    right_column: Mapped[str] = mapped_column(String(128))
    relationship_type: Mapped[str] = mapped_column(String(32), default="many_to_one")
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class QuestionExample(Base):
    __tablename__ = "question_examples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question: Mapped[str] = mapped_column(Text)
    difficulty: Mapped[str] = mapped_column(String(32), index=True)
    expected_query_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_sql: Mapped[str] = mapped_column(Text, default="")
    expected_result: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RuleConstraint(Base):
    __tablename__ = "rule_constraints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rule_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rule_name: Mapped[str] = mapped_column(String(128))
    rule_type: Mapped[str] = mapped_column(String(64), index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
