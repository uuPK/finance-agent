from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.session import engine as default_engine
from app.schemas.metadata import (
    MetadataBusinessTerm,
    MetadataColumn,
    MetadataJoin,
    MetadataMetric,
    MetadataOverview,
    MetadataQuestionExample,
    MetadataTable,
    MetadataTableDetail,
)


class MetadataCatalogService:
    """Read-only catalog used by the metadata center and query-debug workflows."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or default_engine

    def overview(self) -> MetadataOverview:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    """
                    select
                      (select count(*) from metadata.table_metadata where is_active) as table_count,
                      (select count(*) from metadata.column_metadata where is_active)
                        as column_count,
                      (select count(*) from metadata.metric_metadata where is_active)
                        as metric_count,
                      (select count(*) from metadata.business_terms where is_active) as term_count,
                      (select count(*) from metadata.join_relationships where is_active)
                        as join_count,
                      (select count(*) from metadata.question_examples where is_active)
                        as example_count
                    """
                )
            ).mappings().one()
        return MetadataOverview(**dict(row))

    def list_tables(self, search: str | None = None) -> list[MetadataTable]:
        clauses = ["tm.is_active = true"]
        params: dict[str, Any] = {}
        if search:
            clauses.append(
                "(tm.table_name ilike :pattern or tm.display_name ilike :pattern "
                "or tm.domain ilike :pattern)"
            )
            params["pattern"] = f"%{search.strip()}%"
        where = " and ".join(clauses)
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    select tm.schema_name, tm.table_name, tm.display_name, tm.domain,
                           tm.description,
                           tm.grain, tm.refresh_frequency, count(cm.id)::integer as column_count
                    from metadata.table_metadata tm
                    left join metadata.column_metadata cm
                      on cm.schema_name = tm.schema_name and cm.table_name = tm.table_name
                     and cm.is_active = true
                    where {where}
                    group by tm.id
                    order by tm.domain, tm.table_name
                    """
                ),
                params,
            ).mappings().all()
        return [MetadataTable(**dict(row)) for row in rows]

    def get_table(self, table_name: str) -> MetadataTableDetail | None:
        with self.engine.connect() as connection:
            table = connection.execute(
                text(
                    """
                    select schema_name, table_name, display_name, domain, description, grain,
                           refresh_frequency
                    from metadata.table_metadata
                    where table_name = :table_name and is_active = true
                    """
                ),
                {"table_name": table_name},
            ).mappings().first()
            if table is None:
                return None
            columns = connection.execute(
                text(
                    """
                    select schema_name, table_name, column_name, display_name, data_type,
                           description,
                           semantic_type, is_dimension, is_metric_source, is_sensitive
                    from metadata.column_metadata
                    where table_name = :table_name and is_active = true
                    order by id
                    """
                ),
                {"table_name": table_name},
            ).mappings().all()
        return MetadataTableDetail(
            **dict(table),
            column_count=len(columns),
            columns=[MetadataColumn(**dict(column)) for column in columns],
        )

    def list_metrics(self, search: str | None = None) -> list[MetadataMetric]:
        rows = self._list_rows("metric_metadata", search, "metric_code", "metric_name")
        return [MetadataMetric(**row) for row in rows]

    def list_terms(self, search: str | None = None) -> list[MetadataBusinessTerm]:
        rows = self._list_rows("business_terms", search, "term", "definition")
        return [MetadataBusinessTerm(**row) for row in rows]

    def list_joins(self) -> list[MetadataJoin]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    select left_schema, left_table, left_column, right_schema, right_table,
                           right_column, relationship_type, description
                    from metadata.join_relationships
                    where is_active = true
                    order by left_table, right_table
                    """
                )
            ).mappings().all()
        return [MetadataJoin(**dict(row)) for row in rows]

    def list_examples(self, limit: int = 30) -> list[MetadataQuestionExample]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    select question, difficulty, scenario, expected_query_plan, expected_sql, tags
                    from metadata.question_examples
                    where is_active = true
                    order by id desc
                    limit :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()
        return [MetadataQuestionExample(**dict(row)) for row in rows]

    def _list_rows(
        self, table: str, search: str | None, code_column: str, text_column: str
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        where = "is_active = true"
        if search:
            where += f" and ({code_column} ilike :pattern or {text_column} ilike :pattern)"
            params["pattern"] = f"%{search.strip()}%"
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(f"select * from metadata.{table} where {where} order by {code_column}"), params
            ).mappings().all()
        return [dict(row) for row in rows]
