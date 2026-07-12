# ruff: noqa: E501
from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.session import engine as default_engine
from app.guardrails.sql_guardrail import SQLGuardrail
from app.schemas.evaluation import (
    EvaluationDashboard,
    EvaluationResultSummary,
    EvaluationRunDetail,
    EvaluationRunSummary,
    ReviewBatchSummary,
    ReviewDecisionInput,
    ReviewImportResult,
    ReviewItemDetail,
)
from app.schemas.query import QueryRequest, QueryResponse
from app.services.query_service import QueryService
from app.services.run_repository import sanitize_event_payload
from app.services.sql_executor import SQLExecutor


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _canonical(value: Any) -> str:
    def normalize(item: Any) -> Any:
        if isinstance(item, float):
            return round(item, 2)
        if isinstance(item, dict):
            return {key: normalize(value) for key, value in sorted(item.items())}
        if isinstance(item, list):
            return [normalize(value) for value in item]
        return item

    return json.dumps(normalize(value), ensure_ascii=False, sort_keys=True, default=_jsonable)


def _same_result_rows(actual: list[dict[str, Any]], expected: list[dict[str, Any]]) -> bool:
    return sorted(_canonical(row) for row in actual) == sorted(_canonical(row) for row in expected)


class EvaluationRepository:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or default_engine

    def create_run(self, run_name: str, mode: str) -> UUID:
        with self.engine.begin() as connection:
            return connection.execute(
                text(
                    """
                    insert into evaluation.eval_runs
                        (run_name, model_name, status, dataset_version, metadata_version, prompt_version,
                         evaluation_mode)
                    values (:run_name, 'deepseek-chat', 'running', 'synthetic-v1', 'metadata-v1',
                            'query-pipeline-v1', :mode)
                    returning eval_run_id
                    """
                ),
                {"run_name": run_name, "mode": mode},
            ).scalar_one()

    def load_cases(self, difficulty: str | None, limit: int) -> list[dict[str, Any]]:
        where = "where is_active = true"
        params: dict[str, Any] = {"limit": limit}
        if difficulty:
            where += " and difficulty = :difficulty"
            params["difficulty"] = difficulty
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    select case_id, case_code, question, difficulty, expected_query_plan, expected_sql,
                           expected_result, expected_status, scoring_config, tags
                    from evaluation.eval_cases
                    {where}
                    order by case_code
                    limit :limit
                    """
                ),
                params,
            ).mappings().all()
        return [dict(row) for row in rows]

    def save_result(self, eval_run_id: UUID, case: dict[str, Any], result: dict[str, Any]) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    insert into evaluation.eval_results
                        (eval_run_id, case_id, query_id, passed, executable, result_correct,
                         plan_score, sql_score, result_score, elapsed_ms, failure_type, failure_reason,
                         generated_sql, generated_query_plan, generated_response, auto_decision,
                         review_priority, review_status, risk_reasons, critic_confidence)
                    values
                        (:eval_run_id, :case_id, :query_id, :passed, :executable, :result_correct,
                         :plan_score, :sql_score, :result_score, :elapsed_ms, :failure_type,
                         :failure_reason, :generated_sql, cast(:generated_query_plan as jsonb),
                         cast(:generated_response as jsonb), :auto_decision, :review_priority,
                         :review_status, cast(:risk_reasons as jsonb), :critic_confidence)
                    on conflict (eval_run_id, case_id) do update set
                        query_id = excluded.query_id, passed = excluded.passed,
                        executable = excluded.executable, result_correct = excluded.result_correct,
                        plan_score = excluded.plan_score, sql_score = excluded.sql_score,
                        result_score = excluded.result_score, elapsed_ms = excluded.elapsed_ms,
                        failure_type = excluded.failure_type, failure_reason = excluded.failure_reason,
                        generated_sql = excluded.generated_sql,
                        generated_query_plan = excluded.generated_query_plan,
                        generated_response = excluded.generated_response,
                        auto_decision = excluded.auto_decision,
                        review_priority = excluded.review_priority,
                        review_status = excluded.review_status,
                        risk_reasons = excluded.risk_reasons,
                        critic_confidence = excluded.critic_confidence
                    """
                ),
                {
                    "eval_run_id": str(eval_run_id),
                    "case_id": str(case["case_id"]),
                    **result,
                    "generated_query_plan": json.dumps(result["generated_query_plan"], ensure_ascii=False),
                    "generated_response": json.dumps(result["generated_response"], ensure_ascii=False),
                    "risk_reasons": json.dumps(result["risk_reasons"], ensure_ascii=False),
                },
            )

    def finish_run(self, eval_run_id: UUID, status: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    update evaluation.eval_runs run
                    set status = :status,
                        total_cases = stats.total_cases,
                        passed_cases = stats.passed_cases,
                        review_queued_cases = stats.review_queued_cases,
                        average_elapsed_ms = stats.average_elapsed_ms,
                        finished_at = now()
                    from (
                        select count(*)::integer as total_cases,
                               count(*) filter (where passed)::integer as passed_cases,
                               count(*) filter (where review_status = 'pending')::integer as review_queued_cases,
                               avg(elapsed_ms) as average_elapsed_ms
                        from evaluation.eval_results
                        where eval_run_id = :eval_run_id
                    ) stats
                    where run.eval_run_id = :eval_run_id
                    """
                ),
                {"eval_run_id": str(eval_run_id), "status": status},
            )

    def get_run(self, eval_run_id: UUID) -> EvaluationRunDetail | None:
        with self.engine.connect() as connection:
            run = connection.execute(
                text("select * from evaluation.eval_runs where eval_run_id = :eval_run_id"),
                {"eval_run_id": str(eval_run_id)},
            ).mappings().first()
            if run is None:
                return None
            results = connection.execute(
                text(
                    """
                    select er.*, ec.case_code, ec.question, ec.difficulty, ec.expected_status
                    from evaluation.eval_results er
                    join evaluation.eval_cases ec on ec.case_id = er.case_id
                    where er.eval_run_id = :eval_run_id
                    order by ec.case_code
                    """
                ),
                {"eval_run_id": str(eval_run_id)},
            ).mappings().all()
        return EvaluationRunDetail(
            **self._run_summary_payload(run),
            results=[self._result_summary(row) for row in results],
        )

    def list_runs(self, limit: int = 20) -> list[EvaluationRunSummary]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text("select * from evaluation.eval_runs order by started_at desc limit :limit"), {"limit": limit}
            ).mappings().all()
        return [EvaluationRunSummary(**self._run_summary_payload(row)) for row in rows]

    def dashboard(self) -> EvaluationDashboard:
        with self.engine.connect() as connection:
            totals = connection.execute(
                text(
                    """
                    select
                      (select count(*) from evaluation.eval_cases) as total_cases,
                      (select count(*) from evaluation.eval_cases where is_active) as active_cases,
                      count(er.eval_result_id) as total_results,
                      count(er.eval_result_id) filter (where er.executable) as executable_results,
                      count(er.eval_result_id) filter (where er.result_correct) as correct_results,
                      count(er.eval_result_id) filter (where er.passed and coalesce(q.retry_count, 0) = 0) as first_passed,
                      count(er.eval_result_id) filter (where er.passed and coalesce(q.retry_count, 0) > 0) as repaired_passed,
                      avg(er.elapsed_ms) as average_elapsed_ms,
                      count(er.eval_result_id) filter (where er.review_status = 'pending') as pending_review_count,
                      count(er.eval_result_id) filter (where er.review_status = 'reviewed') as reviewed_count
                    from evaluation.eval_results er
                    left join agent.query_runs q on q.query_id = er.query_id
                    """
                )
            ).mappings().one()
            latest = connection.execute(
                text("select * from evaluation.eval_runs order by started_at desc limit 1")
            ).mappings().first()
        total = int(totals["total_results"] or 0)
        def percent(value: Any) -> float:
            return round((float(value or 0) / total) * 100, 1) if total else 0.0

        return EvaluationDashboard(
            total_cases=int(totals["total_cases"]),
            active_cases=int(totals["active_cases"]),
            executable_rate=percent(totals["executable_results"]),
            result_accuracy=percent(totals["correct_results"]),
            first_pass_rate=percent(totals["first_passed"]),
            repaired_pass_rate=percent(totals["repaired_passed"]),
            average_elapsed_ms=float(totals["average_elapsed_ms"]) if totals["average_elapsed_ms"] else None,
            pending_review_count=int(totals["pending_review_count"] or 0),
            reviewed_count=int(totals["reviewed_count"] or 0),
            latest_run=EvaluationRunSummary(**self._run_summary_payload(latest)) if latest else None,
        )

    def create_review_batch(self, batch_name: str, max_items: int, created_by: str) -> ReviewBatchSummary:
        with self.engine.begin() as connection:
            batch = connection.execute(
                text(
                    """
                    insert into evaluation.review_batches (batch_name, dataset_version, created_by)
                    values (:batch_name, 'synthetic-v1', :created_by)
                    returning review_batch_id, batch_name, status, dataset_version, created_at
                    """
                ),
                {"batch_name": batch_name, "created_by": created_by},
            ).mappings().one()
            candidates = connection.execute(
                text(
                    """
                    select eval_result_id, review_priority, risk_reasons
                    from evaluation.eval_results
                    where review_status = 'pending'
                    order by case review_priority when 'blocking' then 1 when 'high' then 2 else 3 end,
                             created_at asc
                    limit :limit
                    """
                ),
                {"limit": max_items},
            ).mappings().all()
            for item in candidates:
                connection.execute(
                    text(
                        """
                        insert into evaluation.review_items
                            (review_batch_id, eval_result_id, priority, risk_reasons)
                        values (:batch_id, :eval_result_id, :priority, cast(:risk_reasons as jsonb))
                        """
                    ),
                    {
                        "batch_id": str(batch["review_batch_id"]),
                        "eval_result_id": str(item["eval_result_id"]),
                        "priority": item["review_priority"] or "normal",
                        "risk_reasons": json.dumps(item["risk_reasons"] or [], ensure_ascii=False),
                    },
                )
            if candidates:
                connection.execute(
                    text(
                        "update evaluation.eval_results set review_status = 'batched' where eval_result_id = any(:ids)"
                    ),
                    {"ids": [str(item["eval_result_id"]) for item in candidates]},
                )
        return ReviewBatchSummary(**dict(batch), item_count=len(candidates))

    def list_review_items(self, batch_id: UUID | None = None, status: str = "pending") -> list[ReviewItemDetail]:
        clause = "where ri.status = :status"
        params: dict[str, Any] = {"status": status}
        if batch_id:
            clause += " and ri.review_batch_id = :batch_id"
            params["batch_id"] = str(batch_id)
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    f"""
                    select ri.review_item_id, ri.review_batch_id, ri.status, ri.priority, ri.risk_reasons,
                           ec.case_code, ec.question, ec.difficulty, ec.expected_status,
                           ec.expected_query_plan, ec.expected_sql, ec.expected_result,
                           er.generated_query_plan, er.generated_sql, er.generated_response,
                           er.auto_decision, er.failure_type, er.failure_reason, er.elapsed_ms
                    from evaluation.review_items ri
                    join evaluation.eval_results er on er.eval_result_id = ri.eval_result_id
                    join evaluation.eval_cases ec on ec.case_id = er.case_id
                    {clause}
                    order by case ri.priority when 'blocking' then 1 when 'high' then 2 else 3 end,
                             ri.created_at
                    """
                ),
                params,
            ).mappings().all()
        return [ReviewItemDetail(**self._review_item_payload(row)) for row in rows]

    def export_review_batch(self, batch_id: UUID, export_format: str) -> tuple[str, bytes]:
        items = self.list_review_items(batch_id)
        if export_format == "jsonl":
            lines = [json.dumps(item.model_dump(mode="json"), ensure_ascii=False) for item in items]
            payload = "\n".join(lines).encode("utf-8")
            content_type = "application/x-ndjson"
        else:
            output = io.StringIO(newline="")
            writer = csv.DictWriter(
                output,
                fieldnames=[
                    "review_item_id", "review_batch_id", "priority", "risk_reasons", "case_code",
                    "question", "difficulty", "expected_status", "auto_decision", "failure_type",
                    "failure_reason", "generated_sql", "reviewer_id", "verdict", "error_class",
                    "severity", "reviewer_note", "confidence",
                ],
            )
            writer.writeheader()
            for item in items:
                row = item.model_dump(mode="json")
                writer.writerow(
                    {
                        **{key: row.get(key) for key in writer.fieldnames if key in row},
                        "risk_reasons": "; ".join(item.risk_reasons),
                        "generated_sql": item.generated_sql or "",
                    }
                )
            payload = ("\ufeff" + output.getvalue()).encode("utf-8")
            content_type = "text/csv; charset=utf-8"
        with self.engine.begin() as connection:
            connection.execute(
                text("update evaluation.review_batches set exported_at = now(), updated_at = now() where review_batch_id = :batch_id"),
                {"batch_id": str(batch_id)},
            )
        return content_type, payload

    def import_decisions(self, decisions: list[ReviewDecisionInput]) -> ReviewImportResult:
        accepted = 0
        rejected: list[str] = []
        with self.engine.begin() as connection:
            for decision in decisions:
                item = connection.execute(
                    text(
                        """
                        select ri.review_item_id, ri.eval_result_id, ri.status, ri.review_batch_id,
                               ec.case_id, ec.question, ec.difficulty
                        from evaluation.review_items ri
                        join evaluation.eval_results er on er.eval_result_id = ri.eval_result_id
                        join evaluation.eval_cases ec on ec.case_id = er.case_id
                        where ri.review_item_id = :review_item_id for update
                        """
                    ),
                    {"review_item_id": str(decision.review_item_id)},
                ).mappings().first()
                if item is None:
                    rejected.append(f"{decision.review_item_id}: review item not found")
                    continue
                if item["status"] == "reviewed":
                    rejected.append(f"{decision.review_item_id}: already reviewed")
                    continue
                checksum = decision.source_checksum or self._decision_checksum(decision)
                connection.execute(
                    text(
                        """
                        insert into evaluation.review_decisions
                            (review_item_id, reviewer_id, verdict, error_class, severity,
                             corrected_query_plan, corrected_sql, corrected_result, reviewer_note,
                             confidence, source_checksum)
                        values (:review_item_id, :reviewer_id, :verdict, :error_class, :severity,
                                cast(:corrected_query_plan as jsonb), :corrected_sql,
                                cast(:corrected_result as jsonb), :reviewer_note, :confidence,
                                :source_checksum)
                        """
                    ),
                    {
                        "review_item_id": str(decision.review_item_id),
                        "reviewer_id": decision.reviewer_id,
                        "verdict": decision.verdict,
                        "error_class": decision.error_class,
                        "severity": decision.severity,
                        "corrected_query_plan": json.dumps(decision.corrected_query_plan, ensure_ascii=False),
                        "corrected_sql": decision.corrected_sql,
                        "corrected_result": json.dumps(decision.corrected_result, ensure_ascii=False),
                        "reviewer_note": decision.reviewer_note,
                        "confidence": decision.confidence,
                        "source_checksum": checksum,
                    },
                )
                self._promote_review_feedback(connection, item, decision)
                connection.execute(
                    text("update evaluation.review_items set status = 'reviewed', updated_at = now() where review_item_id = :review_item_id"),
                    {"review_item_id": str(decision.review_item_id)},
                )
                connection.execute(
                    text("update evaluation.eval_results set review_status = 'reviewed' where eval_result_id = :eval_result_id"),
                    {"eval_result_id": str(item["eval_result_id"])},
                )
                connection.execute(
                    text("update evaluation.review_batches set imported_at = now(), updated_at = now() where review_batch_id = :batch_id"),
                    {"batch_id": str(item["review_batch_id"])},
                )
                accepted += 1
        return ReviewImportResult(accepted=accepted, rejected=rejected)

    def _promote_review_feedback(
        self, connection: Any, item: Any, decision: ReviewDecisionInput
    ) -> None:
        """Promote complete corrected facts into the retrieval and regression corpus.

        A verdict on its own remains an audit record. Only a corrected, read-only SQL
        example (or a confirmed clarification outcome) is used as reusable agent context.
        """
        if decision.verdict == "needs_clarification":
            connection.execute(
                text(
                    """
                    update evaluation.eval_cases
                    set expected_status = 'needs_clarification',
                        expected_query_plan = cast(:plan as jsonb),
                        expected_result = cast(:result as jsonb), updated_at = now()
                    where case_id = :case_id
                    """
                ),
                {
                    "case_id": str(item["case_id"]),
                    "plan": json.dumps(decision.corrected_query_plan, ensure_ascii=False),
                    "result": json.dumps(decision.corrected_result, ensure_ascii=False),
                },
            )
            return
        if decision.verdict != "incorrect" or not decision.corrected_sql:
            return
        guardrail = SQLGuardrail(require_limit=False)
        if not all(finding.passed for finding in guardrail.validate(decision.corrected_sql)):
            return
        expected_result = decision.corrected_result
        if not expected_result:
            execution = SQLExecutor().execute(decision.corrected_sql)
            if execution.status != "success":
                return
            expected_result = {
                "columns": execution.columns,
                "rows": execution.rows,
                "row_count": execution.row_count,
                "comparison": "unordered",
            }
        connection.execute(
            text(
                """
                update evaluation.eval_cases
                set expected_status = 'completed', expected_query_plan = cast(:plan as jsonb),
                    expected_sql = :sql, expected_result = cast(:result as jsonb), updated_at = now()
                where case_id = :case_id
                """
            ),
            {
                "case_id": str(item["case_id"]),
                "plan": json.dumps(decision.corrected_query_plan, ensure_ascii=False),
                "sql": decision.corrected_sql,
                "result": json.dumps(expected_result, ensure_ascii=False),
            },
        )
        connection.execute(
            text(
                """
                insert into metadata.question_examples
                    (question, difficulty, scenario, expected_query_plan, expected_sql,
                     expected_result, tags, is_active)
                values (:question, :difficulty, 'customer_marketing', cast(:plan as jsonb), :sql,
                        cast(:result as jsonb), cast(:tags as jsonb), true)
                """
            ),
            {
                "question": item["question"],
                "difficulty": item["difficulty"],
                "plan": json.dumps(decision.corrected_query_plan, ensure_ascii=False),
                "sql": decision.corrected_sql,
                "result": json.dumps(expected_result, ensure_ascii=False),
                "tags": json.dumps(["human_review", "regression"], ensure_ascii=False),
            },
        )

    @staticmethod
    def _decision_checksum(decision: ReviewDecisionInput) -> str:
        payload = decision.model_dump(mode="json", exclude={"source_checksum"})
        return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()

    @staticmethod
    def _run_summary_payload(row: Any) -> dict[str, Any]:
        return {
            "eval_run_id": row["eval_run_id"],
            "run_name": row["run_name"],
            "status": row["status"],
            "total_cases": row["total_cases"],
            "passed_cases": row["passed_cases"],
            "review_queued_cases": row.get("review_queued_cases", 0),
            "average_elapsed_ms": float(row["average_elapsed_ms"]) if row["average_elapsed_ms"] else None,
            "dataset_version": row.get("dataset_version"),
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }

    @staticmethod
    def _result_summary(row: Any) -> EvaluationResultSummary:
        return EvaluationResultSummary(
            eval_result_id=row["eval_result_id"], case_id=row["case_id"], case_code=row["case_code"],
            question=row["question"], difficulty=row["difficulty"], expected_status=row["expected_status"],
            passed=row["passed"], executable=row["executable"], result_correct=row["result_correct"],
            plan_score=float(row["plan_score"]) if row["plan_score"] is not None else None,
            sql_score=float(row["sql_score"]) if row["sql_score"] is not None else None,
            result_score=float(row["result_score"]) if row["result_score"] is not None else None,
            elapsed_ms=row["elapsed_ms"], failure_type=row["failure_type"], failure_reason=row["failure_reason"],
            auto_decision=row["auto_decision"], review_priority=row["review_priority"],
            review_status=row["review_status"], risk_reasons=list(row["risk_reasons"] or []),
        )

    @staticmethod
    def _review_item_payload(row: Any) -> dict[str, Any]:
        return {
            **dict(row),
            "risk_reasons": list(row["risk_reasons"] or []),
            "expected_query_plan": dict(row["expected_query_plan"] or {}),
            "expected_result": dict(row["expected_result"] or {}),
            "generated_query_plan": dict(row["generated_query_plan"] or {}),
            "generated_response": dict(row["generated_response"] or {}),
        }


class EvaluationManager:
    def __init__(
        self,
        repository: EvaluationRepository | None = None,
        service_factory: Callable[[], QueryService] = QueryService,
    ) -> None:
        self.repository = repository or EvaluationRepository()
        self.service_factory = service_factory
        self.tasks: set[asyncio.Task[None]] = set()

    async def start_run(self, run_name: str, difficulty: str | None, limit: int, mode: str) -> UUID:
        eval_run_id = await asyncio.to_thread(self.repository.create_run, run_name, mode)
        cases = await asyncio.to_thread(self.repository.load_cases, difficulty, limit)
        self._start_task(self._execute(eval_run_id, cases))
        return eval_run_id

    async def _execute(self, eval_run_id: UUID, cases: list[dict[str, Any]]) -> None:
        status = "completed"
        try:
            for case in cases:
                response: QueryResponse | None = None
                error: Exception | None = None
                started_at = perf_counter()
                try:
                    response = await self.service_factory().run(
                        QueryRequest(question=case["question"], user_id="evaluation", include_debug=True)
                    )
                except Exception as exc:  # The failure becomes an auditable evaluation result.
                    error = exc
                elapsed_ms = int((perf_counter() - started_at) * 1000)
                result = self._score(case, response, error, elapsed_ms)
                await asyncio.to_thread(self.repository.save_result, eval_run_id, case, result)
        except Exception:
            status = "failed"
        finally:
            await asyncio.to_thread(self.repository.finish_run, eval_run_id, status)

    def _score(
        self,
        case: dict[str, Any],
        response: QueryResponse | None,
        error: Exception | None,
        elapsed_ms: int,
    ) -> dict[str, Any]:
        if response is None:
            return {
                "query_id": None, "passed": False, "executable": False, "result_correct": False,
                "plan_score": 0.0, "sql_score": 0.0, "result_score": 0.0, "elapsed_ms": elapsed_ms,
                "failure_type": type(error).__name__ if error else "runtime_error",
                "failure_reason": str(error) if error else "Evaluation returned no response.",
                "generated_sql": None, "generated_query_plan": {}, "generated_response": {},
                "auto_decision": "manual_review", "review_priority": "blocking",
                "review_status": "pending", "risk_reasons": ["runtime_error"], "critic_confidence": None,
            }
        generated_plan = response.query_plan.model_dump(mode="json") if response.query_plan else {}
        expected_status = case["expected_status"]
        status_match = response.status == expected_status
        executable = response.status == "completed" and bool(response.sql)
        expected_result = dict(case["expected_result"] or {})
        result_correct = status_match if expected_status == "needs_clarification" else (
            executable and _same_result_rows(response.result_preview, expected_result.get("rows", []))
        )
        plan_score = self._plan_score(case["expected_query_plan"] or {}, generated_plan, status_match)
        sql_score = 100.0 if result_correct else 50.0 if executable else 0.0
        result_score = 100.0 if result_correct else 0.0
        passed = bool(status_match and result_correct)
        confidence = float(generated_plan.get("confidence", 0.0)) if generated_plan else None
        risk_reasons: list[str] = []
        if not status_match:
            risk_reasons.append("status_mismatch")
        if expected_status == "completed" and not executable:
            risk_reasons.append("not_executable")
        if expected_status == "completed" and not result_correct:
            risk_reasons.append("result_mismatch")
        if response.retry_count > 0:
            risk_reasons.append("repaired_execution")
        if case["difficulty"] == "complex":
            risk_reasons.append("complex_case")
        if expected_status == "completed" and confidence is not None and confidence < 0.85:
            risk_reasons.append("low_plan_confidence")
        priority = (
            "blocking" if {"status_mismatch", "not_executable"} & set(risk_reasons)
            else "high" if "result_mismatch" in risk_reasons
            else "normal" if risk_reasons else None
        )
        needs_review = bool(priority)
        return {
            "query_id": str(response.query_id), "passed": passed, "executable": executable,
            "result_correct": result_correct, "plan_score": plan_score, "sql_score": sql_score,
            "result_score": result_score, "elapsed_ms": response.elapsed_ms or elapsed_ms,
            "failure_type": None if passed else response.status,
            "failure_reason": None if passed else response.answer,
            "generated_sql": response.sql, "generated_query_plan": sanitize_event_payload(generated_plan),
            "generated_response": sanitize_event_payload(response.model_dump(mode="json")),
            "auto_decision": "auto_passed" if passed and not needs_review else "manual_review",
            "review_priority": priority, "review_status": "pending" if needs_review else "not_required",
            "risk_reasons": risk_reasons, "critic_confidence": confidence,
        }

    @staticmethod
    def _plan_score(expected: dict[str, Any], actual: dict[str, Any], status_match: bool) -> float:
        if not expected:
            return 100.0 if status_match else 0.0
        matched = 0
        fields = 0
        for key in ("intent", "metrics", "filters", "dimensions", "clarification_fields"):
            if key not in expected:
                continue
            fields += 1
            expected_value = expected[key]
            if key == "metrics":
                actual_value = [item.get("metric_code") for item in actual.get("metrics", [])]
            elif key == "filters":
                actual_value = [
                    f"{item.get('metric_code') or item.get('term')}{item.get('operator')}{item.get('value', {}).get('normalized', item.get('value', {}).get('raw'))}"
                    for item in actual.get("filters", [])
                ]
            elif key == "dimensions":
                actual_value = [item.get("dimension_code") or item.get("name") for item in actual.get("dimensions", [])]
            elif key == "clarification_fields":
                actual_value = [item.get("field") for item in actual.get("clarifications", [])]
            else:
                actual_value = actual.get(key)
            if _canonical(expected_value) == _canonical(actual_value) or (
                isinstance(expected_value, list) and set(expected_value).issubset(set(actual_value or []))
            ):
                matched += 1
        return round((matched / fields) * 100, 2) if fields else 100.0

    def _start_task(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


_manager: EvaluationManager | None = None


def get_evaluation_manager() -> EvaluationManager:
    global _manager
    if _manager is None:
        _manager = EvaluationManager()
    return _manager
