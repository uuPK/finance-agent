from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.db.session import engine as default_engine
from app.schemas.query_plan import QueryPlan


class SchemaContextProvider:
    """Build a compact SQL generation context from PostgreSQL and metadata tables."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or default_engine

    def load(self, query_plan: QueryPlan | None = None) -> dict[str, Any]:
        try:
            with self.engine.connect() as connection:
                return self._load_from_database(connection, query_plan)
        except Exception as exc:
            return self._empty_context(
                source="unavailable",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _load_from_database(
        self, connection: Connection, query_plan: QueryPlan | None
    ) -> dict[str, Any]:
        physical_tables = self._load_physical_tables(connection)
        physical_columns = self._load_physical_columns(connection)
        table_metadata = self._load_table_metadata(connection)
        column_metadata = self._load_column_metadata(connection)
        metrics = self._load_metrics(connection)
        business_terms = self._load_business_terms(connection)
        join_relationships = self._load_join_relationships(connection)
        examples = self._load_question_examples(connection)

        tables: list[dict[str, Any]] = []
        table_allowlist: set[str] = set()
        sensitive_columns: set[str] = set()
        allowed_columns_by_table: dict[str, list[str]] = {}

        for table in physical_tables:
            key = (table["table_schema"], table["table_name"])
            metadata = table_metadata.get(key, {})
            columns = []
            for column in physical_columns.get(key, []):
                column_key = (*key, column["column_name"])
                column_meta = column_metadata.get(column_key, {})
                is_sensitive = bool(column_meta.get("is_sensitive", False))
                if is_sensitive:
                    sensitive_columns.add(column["column_name"])
                columns.append(
                    {
                        "name": column["column_name"],
                        "data_type": column["data_type"],
                        "display_name": column_meta.get("display_name", ""),
                        "description": column_meta.get("description", ""),
                        "semantic_type": column_meta.get("semantic_type"),
                        "is_dimension": bool(column_meta.get("is_dimension", False)),
                        "is_metric_source": bool(column_meta.get("is_metric_source", False)),
                        "is_sensitive": is_sensitive,
                    }
                )

            table_name = table["table_name"]
            table_allowlist.add(table_name)
            allowed_columns_by_table[table_name] = [column["name"] for column in columns]
            tables.append(
                {
                    "schema": table["table_schema"],
                    "name": table_name,
                    "type": table["table_type"],
                    "display_name": metadata.get("display_name", ""),
                    "domain": metadata.get("domain", ""),
                    "grain": metadata.get("grain"),
                    "description": metadata.get("description", ""),
                    "columns": columns,
                }
            )

        return {
            "version": "1.0",
            "source": "database",
            "query_intent": query_plan.intent if query_plan else None,
            "scenario": query_plan.scenario if query_plan else "customer_marketing",
            "table_count": len(tables),
            "metric_count": len(metrics),
            "tables": tables,
            "metrics": metrics,
            "business_terms": business_terms,
            "join_relationships": join_relationships,
            "question_examples": examples,
            "table_allowlist": sorted(table_allowlist),
            "sensitive_columns": sorted(sensitive_columns),
            "allowed_columns_by_table": allowed_columns_by_table,
            "notes": [
                "Use only tables/views and columns listed in this context.",
                "Prefer mart.customer_current_asset for current asset queries.",
                "Prefer mart.customer_trade_90d for recent trade-count queries.",
                "Prefer mart.customer_net_flow_90d for recent net-flow queries.",
            ],
        }

    def _load_physical_tables(self, connection: Connection) -> list[dict[str, Any]]:
        rows = connection.execute(
            text(
                """
                select table_schema, table_name, table_type
                from information_schema.tables
                where table_schema = 'mart'
                  and table_type in ('BASE TABLE', 'VIEW')
                order by table_type, table_name
                """
            )
        ).mappings()
        return [dict(row) for row in rows]

    def _load_physical_columns(
        self, connection: Connection
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        rows = connection.execute(
            text(
                """
                select table_schema, table_name, column_name, data_type, ordinal_position
                from information_schema.columns
                where table_schema = 'mart'
                order by table_schema, table_name, ordinal_position
                """
            )
        ).mappings()

        columns_by_table: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (row["table_schema"], row["table_name"])
            columns_by_table.setdefault(key, []).append(dict(row))
        return columns_by_table

    def _load_table_metadata(
        self, connection: Connection
    ) -> dict[tuple[str, str], dict[str, Any]]:
        rows = self._safe_metadata_rows(
            connection,
            """
            select schema_name, table_name, display_name, domain, description, grain
            from metadata.table_metadata
            where is_active = true
            """,
        )
        return {
            (row["schema_name"], row["table_name"]): dict(row)
            for row in rows
        }

    def _load_column_metadata(
        self, connection: Connection
    ) -> dict[tuple[str, str, str], dict[str, Any]]:
        rows = self._safe_metadata_rows(
            connection,
            """
            select
                schema_name,
                table_name,
                column_name,
                display_name,
                description,
                semantic_type,
                is_dimension,
                is_metric_source,
                is_sensitive
            from metadata.column_metadata
            where is_active = true
            """,
        )
        return {
            (row["schema_name"], row["table_name"], row["column_name"]): dict(row)
            for row in rows
        }

    def _load_metrics(self, connection: Connection) -> list[dict[str, Any]]:
        rows = self._safe_metadata_rows(
            connection,
            """
            select
                metric_code,
                metric_name,
                description,
                formula,
                default_aggregation,
                grain,
                source_tables,
                required_filters
            from metadata.metric_metadata
            where is_active = true
            order by metric_code
            """,
        )
        return [dict(row) for row in rows]

    def _load_business_terms(self, connection: Connection) -> list[dict[str, Any]]:
        rows = self._safe_metadata_rows(
            connection,
            """
            select term, definition, synonyms, default_plan_fragment, clarification_required
            from metadata.business_terms
            where is_active = true
            order by term
            """,
        )
        return [dict(row) for row in rows]

    def _load_join_relationships(self, connection: Connection) -> list[dict[str, Any]]:
        rows = self._safe_metadata_rows(
            connection,
            """
            select
                left_schema,
                left_table,
                left_column,
                right_schema,
                right_table,
                right_column,
                relationship_type,
                description
            from metadata.join_relationships
            where is_active = true
            order by left_table, right_table
            """,
        )
        return [dict(row) for row in rows]

    def _load_question_examples(self, connection: Connection) -> list[dict[str, Any]]:
        rows = self._safe_metadata_rows(
            connection,
            """
            select question, difficulty, expected_sql, tags
            from metadata.question_examples
            where is_active = true
            order by id
            limit 5
            """,
        )
        return [dict(row) for row in rows]

    def _safe_metadata_rows(
        self, connection: Connection, sql: str
    ) -> list[dict[str, Any]]:
        try:
            rows = connection.execute(text(sql)).mappings()
            return [dict(row) for row in rows]
        except Exception:
            return []

    def _empty_context(self, source: str, error: str | None = None) -> dict[str, Any]:
        context: dict[str, Any] = {
            "version": "1.0",
            "source": source,
            "table_count": 0,
            "metric_count": 0,
            "tables": [],
            "metrics": [],
            "business_terms": [],
            "join_relationships": [],
            "question_examples": [],
            "table_allowlist": [],
            "sensitive_columns": [],
            "allowed_columns_by_table": {},
            "notes": [],
        }
        if error:
            context["error"] = error
        return context
