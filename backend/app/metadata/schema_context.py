from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

from app.db.session import engine as default_engine
from app.metadata.retriever import MetadataRetriever
from app.schemas.query_plan import QueryPlan


class SchemaContextProvider:
    """Build a compact SQL generation context from PostgreSQL and metadata tables."""

    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or default_engine

    def load(
        self, query_plan: QueryPlan | None = None, question: str | None = None
    ) -> dict[str, Any]:
        try:
            with self.engine.connect() as connection:
                return self._load_from_database(connection, query_plan, question)
        except Exception as exc:
            return self._empty_context(
                source="unavailable",
                error=f"{type(exc).__name__}: {exc}",
            )

    def _load_from_database(
        self,
        connection: Connection,
        query_plan: QueryPlan | None,
        question: str | None,
    ) -> dict[str, Any]:
        physical_tables = self._load_physical_tables(connection)
        physical_columns = self._load_physical_columns(connection)
        table_metadata = self._load_table_metadata(connection)
        column_metadata = self._load_column_metadata(connection)
        metrics = self._load_metrics(connection)
        business_terms = self._load_business_terms(connection)
        join_relationships = self._load_join_relationships(connection)
        examples = self._load_question_examples(connection)
        reference_date = self._load_reference_date(connection)
        retrieval = MetadataRetriever(connection).retrieve(
            question=question, query_plan=query_plan
        )
        selected_table_names = set(retrieval.table_names)
        selected_table_names.update(self._required_semantic_tables(question, query_plan))
        selected_metric_codes = set(retrieval.metric_codes)
        selected_terms = set(retrieval.business_terms)
        selected_examples = {
            row.get("question")
            for row in retrieval.matched_question_examples
            if isinstance(row.get("question"), str)
        }
        selected_join_pairs = {
            (
                row.get("left_table"),
                row.get("left_column"),
                row.get("right_table"),
                row.get("right_column"),
            )
            for row in retrieval.matched_join_relationships
        }

        tables: list[dict[str, Any]] = []
        table_allowlist: set[str] = set()
        sensitive_columns: set[str] = set()
        allowed_columns_by_table: dict[str, list[str]] = {}

        for table in physical_tables:
            table_name = table["table_name"]
            if selected_table_names and table_name not in selected_table_names:
                continue

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

        selected_metrics = [
            metric
            for metric in metrics
            if not selected_metric_codes or metric.get("metric_code") in selected_metric_codes
        ]
        selected_business_terms = [
            term
            for term in business_terms
            if selected_terms and term.get("term") in selected_terms
        ]
        selected_join_relationships = [
            relationship
            for relationship in join_relationships
            if not selected_join_pairs
            or (
                relationship.get("left_table"),
                relationship.get("left_column"),
                relationship.get("right_table"),
                relationship.get("right_column"),
            )
            in selected_join_pairs
        ]
        selected_question_examples = [
            example
            for example in examples
            if not selected_examples or example.get("question") in selected_examples
        ]

        return {
            "version": "1.0",
            "source": "database",
            "query_intent": query_plan.intent if query_plan else None,
            "scenario": query_plan.scenario if query_plan else "customer_marketing",
            "table_count": len(tables),
            "metric_count": len(selected_metrics),
            "retrieval": retrieval.to_context(),
            "tables": tables,
            "metrics": selected_metrics,
            "business_terms": selected_business_terms,
            "join_relationships": selected_join_relationships,
            "question_examples": selected_question_examples,
            "table_allowlist": sorted(table_allowlist),
            "sensitive_columns": sorted(sensitive_columns),
            "allowed_columns_by_table": allowed_columns_by_table,
            "semantic_contract": self._semantic_contract(
                table_allowlist, selected_metrics, sensitive_columns, reference_date
            ),
            "notes": [
                "Use only retrieved tables/views and columns listed in this context.",
                "The retrieval field explains why this metadata context was selected.",
                "Prefer mart.customer_current_asset for current asset queries.",
                "Prefer mart.customer_trade_90d for recent trade-count queries.",
                "Prefer mart.customer_net_flow_90d for recent net-flow queries.",
            ],
        }

    @staticmethod
    def _required_semantic_tables(
        question: str | None, query_plan: QueryPlan | None
    ) -> set[str]:
        """Add the verified physical grain required by unambiguous business semantics."""
        if query_plan is None:
            return set()

        metric_codes = {metric.metric_code for metric in query_plan.metrics}
        dimension_codes = {dimension.dimension_code for dimension in query_plan.dimensions}
        required: set[str] = set()
        if "product_type" in dimension_codes and "trade_amount_90d" in metric_codes:
            required.update({"customer_trade", "product_info"})
        if question and "净流出" in question:
            required.update({"customer_info", "customer_net_flow_90d"})
        return required

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
            select question, difficulty, expected_query_plan, expected_sql, tags
            from metadata.question_examples
            where is_active = true
            order by id
            limit 5
            """,
        )
        return [dict(row) for row in rows]

    def _load_reference_date(self, connection: Connection) -> str | None:
        row = connection.execute(
            text("select max(as_of_date)::text as reference_date from mart.customer_asset_daily")
        ).mappings().first()
        return row["reference_date"] if row and row["reference_date"] else None

    @staticmethod
    def _semantic_contract(
        table_allowlist: set[str],
        metrics: list[dict[str, Any]],
        sensitive_columns: set[str],
        reference_date: str | None,
    ) -> dict[str, Any]:
        """Explicit execution rules that prevent an LLM from guessing table semantics."""
        rules: list[str] = []
        if "customer_trade_90d" in table_allowlist:
            rules.append(
                "customer_trade_90d is already aggregated by customer for the latest 90-day "
                "window; "
                "do not add a raw trade_date filter to this view."
            )
        if "customer_net_flow_90d" in table_allowlist:
            rules.append(
                "customer_net_flow_90d is already aggregated by customer for the latest 90-day "
                "window; "
                "net_flow_amount_90d is positive for inflow and negative for outflow."
            )
            rules.append(
                "For a net-outflow ranking, filter net_flow_amount_90d < 0, return "
                "-net_flow_amount_90d, and order that positive outflow amount descending."
            )
        if {"customer_position_daily", "product_info"} <= table_allowlist:
            rules.append(
                "For customers without a product type, use NOT EXISTS with customer, product-type, "
                "and same-snapshot predicates. Do not infer absence from a LEFT JOIN null check."
            )
        if "customer_trade" in table_allowlist:
            rules.append(
                "Use customer_trade, not customer_trade_90d, for product-level trade amount or "
                "product-level customer counts because product_id and trade_date are required."
            )
        if {"marketing_campaign", "marketing_touch"} <= table_allowlist:
            rules.append(
                "For campaign response_rate, use responded touch count divided by all touch count "
                "unless the QueryPlan explicitly requests a customer-based denominator."
            )
            rules.append(
                "For campaign benchmark output, use campaign_code as the stable campaign "
                "dimension, "
                "not campaign_name."
            )
            rules.append(
                "For response_rate, use COUNT(*) FILTER (WHERE response_status = 'responded') "
                "/ COUNT(*) over campaign touches. Do not reuse the distinct-customer denominator."
            )
        if reference_date:
            rules.append(
                "For relative-time SQL over this dataset, use the reference_date value below "
                "instead "
                "of CURRENT_DATE so results align with the latest loaded snapshot."
            )
        return {
            "rules": rules,
            "metric_formulas": {
                metric["metric_code"]: metric.get("formula")
                for metric in metrics
                if metric.get("metric_code") and metric.get("formula")
            },
            "metric_output_aliases": {
                "current_total_asset": ["current_total_asset", "total_asset"],
                "net_asset_inflow_90d": ["net_asset_inflow_90d", "net_flow_amount_90d"],
                "trade_amount_90d": ["trade_amount_90d", "trade_amount"],
                "fund_holding_amount": ["fund_holding_amount", "market_value"],
            },
            "reference_date": reference_date,
            "sensitive_columns_never_select": sorted(sensitive_columns),
        }

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
            "retrieval": {
                "strategy": "structured_keyword_retrieval",
                "keywords": [],
                "table_names": [],
                "metric_codes": [],
                "business_terms": [],
                "confidence": 0.0,
            },
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
