from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.session import engine as default_engine
from app.schemas.metadata import (
    MetadataBusinessTerm,
    MetadataBusinessTermInput,
    MetadataChangeInput,
    MetadataColumn,
    MetadataJoin,
    MetadataJoinInput,
    MetadataMetric,
    MetadataMetricInput,
    MetadataOverview,
    MetadataQuestionExample,
    MetadataQuestionExampleInput,
    MetadataRuleConstraint,
    MetadataRuleConstraintInput,
    MetadataTable,
    MetadataTableDetail,
)


class MetadataCatalogService:
    """Catalog with read-only physical-schema views and editable semantic metadata."""

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
                    select id, left_schema, left_table, left_column, right_schema, right_table,
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
                    select id, question, difficulty, scenario, expected_query_plan, expected_sql,
                           expected_result, tags
                    from metadata.question_examples
                    where is_active = true
                    order by id desc
                    limit :limit
                    """
                ),
                {"limit": limit},
            ).mappings().all()
        return [MetadataQuestionExample(**dict(row)) for row in rows]

    def list_rules(self) -> list[MetadataRuleConstraint]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    """
                    select rule_code, rule_name, rule_type, config, severity, description
                    from metadata.rule_constraints
                    where is_active = true
                    order by rule_code
                    """
                )
            ).mappings().all()
        return [MetadataRuleConstraint(**dict(row)) for row in rows]

    def create_metric(self, payload: MetadataMetricInput) -> MetadataMetric:
        with self.engine.begin() as connection:
            return self._write_metric(connection, payload, create=True)

    def update_metric(self, metric_code: str, payload: MetadataMetricInput) -> MetadataMetric:
        if payload.metric_code != metric_code:
            raise ValueError("Metric code is an immutable identifier; create a new metric instead.")
        with self.engine.begin() as connection:
            return self._write_metric(connection, payload, create=False)

    def deactivate_metric(self, metric_code: str) -> None:
        self._deactivate("metric_metadata", "metric_code", metric_code)

    def create_term(self, payload: MetadataBusinessTermInput) -> MetadataBusinessTerm:
        with self.engine.begin() as connection:
            return self._write_term(connection, payload, create=True)

    def update_term(self, term: str, payload: MetadataBusinessTermInput) -> MetadataBusinessTerm:
        if payload.term != term:
            raise ValueError("Business term is an immutable identifier; create a new term instead.")
        with self.engine.begin() as connection:
            return self._write_term(connection, payload, create=False)

    def deactivate_term(self, term: str) -> None:
        self._deactivate("business_terms", "term", term)

    def create_join(self, payload: MetadataJoinInput) -> MetadataJoin:
        with self.engine.begin() as connection:
            return self._write_join(connection, payload, join_id=None)

    def update_join(self, join_id: int, payload: MetadataJoinInput) -> MetadataJoin:
        with self.engine.begin() as connection:
            return self._write_join(connection, payload, join_id=join_id)

    def deactivate_join(self, join_id: int) -> None:
        self._deactivate("join_relationships", "id", join_id)

    def create_example(self, payload: MetadataQuestionExampleInput) -> MetadataQuestionExample:
        with self.engine.begin() as connection:
            return self._write_example(connection, payload, example_id=None)

    def update_example(
        self, example_id: int, payload: MetadataQuestionExampleInput
    ) -> MetadataQuestionExample:
        with self.engine.begin() as connection:
            return self._write_example(connection, payload, example_id=example_id)

    def deactivate_example(self, example_id: int) -> None:
        self._deactivate("question_examples", "id", example_id)

    def create_rule(self, payload: MetadataRuleConstraintInput) -> MetadataRuleConstraint:
        with self.engine.begin() as connection:
            return self._write_rule(connection, payload, create=True)

    def update_rule(
        self, rule_code: str, payload: MetadataRuleConstraintInput
    ) -> MetadataRuleConstraint:
        if payload.rule_code != rule_code:
            raise ValueError("Rule code is an immutable identifier; create a new rule instead.")
        with self.engine.begin() as connection:
            return self._write_rule(connection, payload, create=False)

    def deactivate_rule(self, rule_code: str) -> None:
        self._deactivate("rule_constraints", "rule_code", rule_code)

    def apply_review_changes(
        self, connection: Any, changes: list[MetadataChangeInput]
    ) -> int:
        """Persist reviewer-selected semantic metadata using the review transaction."""
        for change in changes:
            if change.kind == "metric":
                payload = MetadataMetricInput.model_validate(change.payload)
                self._write_metric(connection, payload, create=change.action == "create")
            elif change.kind == "term":
                payload = MetadataBusinessTermInput.model_validate(change.payload)
                self._write_term(connection, payload, create=change.action == "create")
            elif change.kind == "join":
                payload = MetadataJoinInput.model_validate(change.payload)
                join_id = change.payload.get("id") if change.action == "update" else None
                if not isinstance(join_id, int):
                    raise ValueError("Updating a join requires its numeric id.")
                self._write_join(connection, payload, join_id=join_id)
            elif change.kind == "example":
                payload = MetadataQuestionExampleInput.model_validate(change.payload)
                example_id = change.payload.get("id") if change.action == "update" else None
                if change.action == "update" and not isinstance(example_id, int):
                    raise ValueError("Updating an example requires its numeric id.")
                self._write_example(connection, payload, example_id=example_id)
            else:
                payload = MetadataRuleConstraintInput.model_validate(change.payload)
                self._write_rule(connection, payload, create=change.action == "create")
        return len(changes)

    def _write_metric(
        self, connection: Any, payload: MetadataMetricInput, create: bool
    ) -> MetadataMetric:
        self._validate_source_tables(connection, payload.source_tables)
        params = {
            **payload.model_dump(),
            "source_tables": json.dumps(payload.source_tables),
            "required_filters": json.dumps(payload.required_filters),
        }
        if create:
            self._assert_absent(connection, "metric_metadata", "metric_code", payload.metric_code)
            connection.execute(
                text(
                    """
                    insert into metadata.metric_metadata
                        (metric_code, metric_name, description, formula, default_aggregation, grain,
                         source_tables, required_filters, owner, is_active)
                    values (:metric_code, :metric_name, :description, :formula,
                            :default_aggregation, :grain, cast(:source_tables as jsonb),
                            cast(:required_filters as jsonb), :owner, true)
                    """
                ),
                params,
            )
        else:
            self._assert_active(connection, "metric_metadata", "metric_code", payload.metric_code)
            connection.execute(
                text(
                    """
                    update metadata.metric_metadata
                    set metric_name = :metric_name, description = :description, formula = :formula,
                        default_aggregation = :default_aggregation, grain = :grain,
                        source_tables = cast(:source_tables as jsonb),
                        required_filters = cast(:required_filters as jsonb), owner = :owner,
                        updated_at = now()
                    where metric_code = :metric_code
                    """
                ),
                params,
            )
        row = self._one_row(
            connection,
            "select * from metadata.metric_metadata where metric_code = :code",
            {"code": payload.metric_code},
        )
        return MetadataMetric(**row)

    def _write_term(
        self, connection: Any, payload: MetadataBusinessTermInput, create: bool
    ) -> MetadataBusinessTerm:
        params = {
            **payload.model_dump(),
            "synonyms": json.dumps(payload.synonyms, ensure_ascii=False),
            "default_plan_fragment": json.dumps(
                payload.default_plan_fragment, ensure_ascii=False
            ),
        }
        if create:
            self._assert_absent(connection, "business_terms", "term", payload.term)
            connection.execute(
                text(
                    """
                    insert into metadata.business_terms
                        (term, definition, synonyms, default_plan_fragment,
                         clarification_required, is_active)
                    values (:term, :definition, cast(:synonyms as jsonb),
                            cast(:default_plan_fragment as jsonb), :clarification_required, true)
                    """
                ),
                params,
            )
        else:
            self._assert_active(connection, "business_terms", "term", payload.term)
            connection.execute(
                text(
                    """
                    update metadata.business_terms
                    set definition = :definition, synonyms = cast(:synonyms as jsonb),
                        default_plan_fragment = cast(:default_plan_fragment as jsonb),
                        clarification_required = :clarification_required, updated_at = now()
                    where term = :term
                    """
                ),
                params,
            )
        row = self._one_row(
            connection,
            "select * from metadata.business_terms where term = :term",
            {"term": payload.term},
        )
        return MetadataBusinessTerm(**row)

    def _write_join(
        self, connection: Any, payload: MetadataJoinInput, join_id: int | None
    ) -> MetadataJoin:
        self._validate_join_endpoint(
            connection, payload.left_schema, payload.left_table, payload.left_column
        )
        self._validate_join_endpoint(
            connection, payload.right_schema, payload.right_table, payload.right_column
        )
        params = payload.model_dump()
        if join_id is None:
            row = connection.execute(
                text(
                    """
                    insert into metadata.join_relationships
                        (left_schema, left_table, left_column, right_schema, right_table,
                         right_column, relationship_type, description, is_active)
                    values (:left_schema, :left_table, :left_column, :right_schema, :right_table,
                            :right_column, :relationship_type, :description, true)
                    returning id
                    """
                ),
                params,
            ).mappings().one()
            join_id = int(row["id"])
        else:
            self._assert_active(connection, "join_relationships", "id", join_id)
            connection.execute(
                text(
                    """
                    update metadata.join_relationships
                    set left_schema = :left_schema, left_table = :left_table,
                        left_column = :left_column, right_schema = :right_schema,
                        right_table = :right_table, right_column = :right_column,
                        relationship_type = :relationship_type, description = :description,
                        updated_at = now()
                    where id = :id
                    """
                ),
                {**params, "id": join_id},
            )
        row = self._one_row(
            connection,
            "select id, left_schema, left_table, left_column, right_schema, right_table, "
            "right_column, relationship_type, description from metadata.join_relationships "
            "where id = :id",
            {"id": join_id},
        )
        return MetadataJoin(**row)

    def _write_example(
        self,
        connection: Any,
        payload: MetadataQuestionExampleInput,
        example_id: int | None,
    ) -> MetadataQuestionExample:
        params = {
            **payload.model_dump(),
            "expected_query_plan": json.dumps(payload.expected_query_plan, ensure_ascii=False),
            "expected_result": json.dumps(payload.expected_result, ensure_ascii=False),
            "tags": json.dumps(payload.tags, ensure_ascii=False),
        }
        if example_id is None:
            row = connection.execute(
                text(
                    """
                    insert into metadata.question_examples
                        (question, difficulty, scenario, expected_query_plan, expected_sql,
                         expected_result, tags, is_active)
                    values (:question, :difficulty, :scenario, cast(:expected_query_plan as jsonb),
                            :expected_sql, cast(:expected_result as jsonb),
                            cast(:tags as jsonb), true)
                    returning id
                    """
                ),
                params,
            ).mappings().one()
            example_id = int(row["id"])
        else:
            self._assert_active(connection, "question_examples", "id", example_id)
            connection.execute(
                text(
                    """
                    update metadata.question_examples
                    set question = :question, difficulty = :difficulty, scenario = :scenario,
                        expected_query_plan = cast(:expected_query_plan as jsonb),
                        expected_sql = :expected_sql,
                        expected_result = cast(:expected_result as jsonb),
                        tags = cast(:tags as jsonb), updated_at = now()
                    where id = :id
                    """
                ),
                {**params, "id": example_id},
            )
        row = self._one_row(
            connection,
            "select id, question, difficulty, scenario, expected_query_plan, expected_sql, "
            "expected_result, tags from metadata.question_examples where id = :id",
            {"id": example_id},
        )
        return MetadataQuestionExample(**row)

    def _write_rule(
        self, connection: Any, payload: MetadataRuleConstraintInput, create: bool
    ) -> MetadataRuleConstraint:
        params = {**payload.model_dump(), "config": json.dumps(payload.config, ensure_ascii=False)}
        if create:
            self._assert_absent(connection, "rule_constraints", "rule_code", payload.rule_code)
            connection.execute(
                text(
                    """
                    insert into metadata.rule_constraints
                        (rule_code, rule_name, rule_type, config, severity, description, is_active)
                    values (:rule_code, :rule_name, :rule_type, cast(:config as jsonb),
                            :severity, :description, true)
                    """
                ),
                params,
            )
        else:
            self._assert_active(connection, "rule_constraints", "rule_code", payload.rule_code)
            connection.execute(
                text(
                    """
                    update metadata.rule_constraints
                    set rule_name = :rule_name, rule_type = :rule_type,
                        config = cast(:config as jsonb), severity = :severity,
                        description = :description, updated_at = now()
                    where rule_code = :rule_code
                    """
                ),
                params,
            )
        row = self._one_row(
            connection,
            "select rule_code, rule_name, rule_type, config, severity, description "
            "from metadata.rule_constraints where rule_code = :code",
            {"code": payload.rule_code},
        )
        return MetadataRuleConstraint(**row)

    def _deactivate(self, table: str, key_column: str, key: str | int) -> None:
        with self.engine.begin() as connection:
            self._assert_active(connection, table, key_column, key)
            connection.execute(
                text(
                    f"update metadata.{table} set is_active = false, updated_at = now() "
                    f"where {key_column} = :key"
                ),
                {"key": key},
            )

    @staticmethod
    def _one_row(connection: Any, query: str, params: dict[str, Any]) -> dict[str, Any]:
        row = connection.execute(text(query), params).mappings().one()
        return dict(row)

    @staticmethod
    def _assert_absent(connection: Any, table: str, key_column: str, key: str | int) -> None:
        row = connection.execute(
            text(f"select 1 from metadata.{table} where {key_column} = :key"), {"key": key}
        ).first()
        if row is not None:
            raise ValueError(f"Metadata identifier already exists: {key}")

    @staticmethod
    def _assert_active(connection: Any, table: str, key_column: str, key: str | int) -> None:
        row = connection.execute(
            text(f"select is_active from metadata.{table} where {key_column} = :key"),
            {"key": key},
        ).mappings().first()
        if row is None:
            raise LookupError(f"Metadata record not found: {key}")
        if not row["is_active"]:
            raise ValueError(f"Metadata record is already inactive: {key}")

    @staticmethod
    def _validate_source_tables(connection: Any, table_names: list[str]) -> None:
        for table_name in table_names:
            row = connection.execute(
                text(
                    """
                    select 1 from information_schema.tables
                    where table_schema = 'mart' and table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            ).first()
            if row is None:
                raise ValueError(f"Metric source table does not exist in mart: {table_name}")

    @staticmethod
    def _validate_join_endpoint(
        connection: Any, schema_name: str, table_name: str, column_name: str
    ) -> None:
        if schema_name != "mart":
            raise ValueError("Manual join metadata may reference only the mart schema.")
        row = connection.execute(
            text(
                """
                select 1 from information_schema.columns
                where table_schema = :schema_name and table_name = :table_name
                  and column_name = :column_name
                """
            ),
            {
                "schema_name": schema_name,
                "table_name": table_name,
                "column_name": column_name,
            },
        ).first()
        if row is None:
            raise ValueError(
                "Join field does not exist in the official schema: "
                f"{schema_name}.{table_name}.{column_name}"
            )

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
