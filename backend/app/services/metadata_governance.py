"""Human-reviewed metadata candidates and fail-closed promotion lifecycle."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.session import engine as default_engine
from app.evaluation.ablation import database_fingerprint
from app.guardrails.sql_guardrail import SQLGuardrail
from app.metadata.schema_context import SchemaContextProvider
from app.schemas.evaluation import ReviewDecisionInput
from app.schemas.metadata import MetadataChangeInput
from app.services.metadata_catalog_service import MetadataCatalogService


class MetadataGovernanceService:
    def __init__(self, engine: Engine | None = None) -> None:
        self.engine = engine or default_engine
        self.catalog = MetadataCatalogService(self.engine)

    def stage_review_decision(
        self, connection: Any, item: dict[str, Any], decision: ReviewDecisionInput
    ) -> int:
        """An imported review creates candidates only; active metadata stays untouched."""
        changes = list(decision.metadata_changes)
        override: dict[str, Any] | None = None
        if (
            item.get("case_id") is not None
            and decision.verdict == "incorrect"
            and decision.corrected_sql
        ):
            if not decision.corrected_query_plan:
                raise ValueError("Corrected SQL needs a reviewer-supplied QueryPlan.")
            if not isinstance(decision.corrected_result.get("rows"), list):
                raise ValueError(
                    "Corrected SQL needs reviewer-supplied result rows before staging."
                )
            self._validate_reference_sql(decision.corrected_sql)
            override = {
                "case_id": str(item["case_id"]),
                "expected_status": "completed",
                "expected_query_plan": decision.corrected_query_plan,
                "expected_sql": decision.corrected_sql,
                "expected_result": decision.corrected_result,
            }
            changes.append(MetadataChangeInput(
                kind="example", action="create", payload={
                    "question": item["question"], "difficulty": item["difficulty"],
                    "scenario": "customer_marketing",
                    "expected_query_plan": decision.corrected_query_plan,
                    "expected_sql": decision.corrected_sql,
                    "expected_result": decision.corrected_result,
                    "tags": ["human_review", "regression"],
                },
            ))
        elif item.get("case_id") is not None and decision.verdict == "needs_clarification":
            if not decision.corrected_query_plan:
                raise ValueError("Clarification correction requires a reviewed QueryPlan.")
            override = {
                "case_id": str(item["case_id"]),
                "expected_status": "needs_clarification",
                "expected_query_plan": decision.corrected_query_plan,
                "expected_sql": None,
                "expected_result": decision.corrected_result,
            }

        candidates: list[tuple[str, str, str, dict[str, Any]]] = []
        seen: set[tuple[str, str]] = set()
        for change in changes:
            self.catalog.validate_candidate_change(connection, change)
            if change.kind == "example" and change.payload.get("expected_sql"):
                self._validate_reference_sql(str(change.payload["expected_sql"]))
            key = self.catalog.candidate_key(change)
            identity = (change.kind, key)
            if identity in seen:
                raise ValueError(f"Duplicate metadata candidate in one review: {identity}.")
            seen.add(identity)
            payload = dict(change.payload)
            if item.get("case_id") is not None:
                payload["_source_case_id"] = str(item["case_id"])
            if override is not None:
                payload["_case_override"] = override
            candidates.append((change.kind, change.action, key, payload))
        if override is not None:
            candidates.append((
                "case_correction", "update", override["case_id"], override,
            ))
        for kind, action, key, payload in candidates:
            previous = connection.execute(text("""
                select candidate_id from metadata.metadata_candidates
                where kind = :kind and entity_key = :entity_key and status = 'promoted'
                order by promoted_at desc limit 1
            """), {"kind": kind, "entity_key": key}).scalar_one_or_none()
            connection.execute(text("""
                insert into metadata.metadata_candidates
                    (kind, action, entity_key, payload, source_review_item_id,
                     source_query_id, reviewer_id, supersedes)
                values (:kind, :action, :entity_key, cast(:payload as jsonb),
                        :review_item_id, :source_query_id, :reviewer_id, :supersedes)
            """), {
                "kind": kind, "action": action, "entity_key": key,
                "payload": json.dumps(payload, ensure_ascii=False),
                "review_item_id": str(item["review_item_id"]),
                "source_query_id": str(item["source_query_id"])
                if item.get("source_query_id") else None,
                "reviewer_id": decision.reviewer_id,
                "supersedes": str(previous) if previous else None,
            })
        return len(candidates)

    def _validate_reference_sql(self, sql: str) -> None:
        context = SchemaContextProvider(self.engine).load()
        if context.get("source") != "database":
            raise ValueError("Cannot validate corrected SQL without live schema metadata.")
        guardrail = SQLGuardrail.from_metadata_context(context, require_limit=False)
        failures = [item for item in guardrail.validate(sql) if not item.passed]
        if failures:
            raise ValueError("Corrected SQL failed the read-only/schema guardrail.")

    def list_candidates(self, status: str | None = None) -> list[dict[str, Any]]:
        where = "where status = :status" if status is not None else ""
        with self.engine.connect() as connection:
            rows = connection.execute(text(f"""
                select * from metadata.metadata_candidates
                {where}
                order by created_at desc limit 200
            """), {"status": status}).mappings().all()
        return [dict(row) for row in rows]

    def get_candidate(self, candidate_id: UUID) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text("""
                select * from metadata.metadata_candidates where candidate_id = :candidate_id
            """), {"candidate_id": str(candidate_id)}).mappings().first()
        return dict(row) if row else None

    def approve(self, candidate_id: UUID, approved_by: str) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate = self._locked(connection, candidate_id)
            self._require_status(candidate, "candidate")
            if approved_by == candidate["reviewer_id"]:
                raise ValueError("A different person must approve the reviewer's candidate.")
            connection.execute(text("""
                update metadata.metadata_candidates
                set status = 'approved', approved_by = :approved_by, approved_at = now()
                where candidate_id = :candidate_id
            """), {"candidate_id": str(candidate_id), "approved_by": approved_by})
        return self.get_candidate(candidate_id) or {}

    def reject(self, candidate_id: UUID, reason: str) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate = self._locked(connection, candidate_id)
            if candidate["status"] not in {"candidate", "approved", "ready"}:
                raise ValueError("Only an unpromoted, idle candidate can be rejected.")
            connection.execute(text("""
                update metadata.metadata_candidates
                set status = 'rejected', regression_report = cast(:report as jsonb)
                where candidate_id = :candidate_id
            """), {
                "candidate_id": str(candidate_id),
                "report": json.dumps({"passed": False, "reason": reason}),
            })
        return self.get_candidate(candidate_id) or {}

    def begin_regression(
        self, candidate_id: UUID, baseline_run_id: UUID, regression_run_id: UUID
    ) -> None:
        with self.engine.begin() as connection:
            candidate = self._locked(connection, candidate_id)
            self._require_status(candidate, "approved")
            connection.execute(text("""
                update metadata.metadata_candidates
                set status = 'evaluating', baseline_eval_run_id = :baseline_id,
                    regression_eval_run_id = :run_id, regression_report = null
                where candidate_id = :candidate_id
            """), {
                "candidate_id": str(candidate_id), "baseline_id": str(baseline_run_id),
                "run_id": str(regression_run_id),
            })

    def finish_regression(self, candidate_id: UUID) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate = self._locked(connection, candidate_id)
            self._require_status(candidate, "evaluating")
            baseline = self._run_results(connection, candidate["baseline_eval_run_id"])
            current = self._run_results(connection, candidate["regression_eval_run_id"])
            report = self._regression_report(candidate, baseline, current)
            connection.execute(text("""
                update metadata.metadata_candidates
                set status = :status, regression_report = cast(:report as jsonb)
                where candidate_id = :candidate_id
            """), {
                "candidate_id": str(candidate_id),
                "status": "ready" if report["passed"] else "rejected",
                "report": json.dumps(report),
            })
        return self.get_candidate(candidate_id) or {}

    def promote(self, candidate_id: UUID) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate = self._locked(connection, candidate_id)
            self._require_status(candidate, "ready")
            if not (candidate["regression_report"] or {}).get("passed"):
                raise ValueError("Candidate has no passing regression evidence.")
            baseline = connection.execute(text("""
                select comparison_manifest from evaluation.eval_runs
                where eval_run_id = :run_id and status = 'completed'
            """), {"run_id": str(candidate["baseline_eval_run_id"])}).mappings().first()
            if not baseline or not baseline["comparison_manifest"]:
                raise ValueError("Completed pinned baseline is unavailable.")
            baseline_evidence = self._run_results(connection, candidate["baseline_eval_run_id"])
            regression = self._run_results(connection, candidate["regression_eval_run_id"])
            current_report = self._regression_report(candidate, baseline_evidence, regression)
            if current_report != candidate["regression_report"]:
                raise ValueError("Candidate regression evidence changed after approval.")
            if (
                database_fingerprint(self.engine)
                != baseline["comparison_manifest"]["database_sha256"]
            ):
                raise ValueError("Production database changed after regression; rerun baseline.")
            latest = connection.execute(text("""
                select candidate_id from metadata.metadata_candidates
                where kind = :kind and entity_key = :entity_key and status = 'promoted'
                order by promoted_at desc limit 1
            """), {
                "kind": candidate["kind"], "entity_key": candidate["entity_key"],
            }).scalar_one_or_none()
            latest_id = str(latest) if latest else None
            expected_id = str(candidate["supersedes"]) if candidate["supersedes"] else None
            if latest_id != expected_id:
                raise ValueError("A newer version superseded this candidate.")
            kind = candidate["kind"]
            payload = dict(candidate["payload"])
            if kind == "case_correction":
                existing = connection.execute(text("""
                    select to_jsonb(c) as payload from evaluation.eval_cases c
                    where case_id = :case_id for update
                """), {"case_id": candidate["entity_key"]}).mappings().one()
                previous = dict(existing["payload"])
                connection.execute(text("""
                    update evaluation.eval_cases
                    set expected_status = :status, expected_sql = :sql,
                        expected_query_plan = cast(:plan as jsonb),
                        expected_result = cast(:result as jsonb), updated_at = now()
                    where case_id = :case_id
                """), {
                    "case_id": candidate["entity_key"], "status": payload["expected_status"],
                    "sql": payload.get("expected_sql"),
                    "plan": json.dumps(payload["expected_query_plan"], ensure_ascii=False),
                    "result": json.dumps(payload["expected_result"], ensure_ascii=False),
                })
                entity_id = candidate["entity_key"]
            else:
                change = MetadataChangeInput(
                    kind=kind, action=candidate["action"], payload=payload
                )
                self.catalog.validate_candidate_change(connection, change)
                if kind == "example" and payload.get("expected_sql"):
                    self._validate_reference_sql(str(payload["expected_sql"]))
                previous = (
                    self.catalog.candidate_previous_row(connection, kind, candidate["entity_key"])
                    if candidate["action"] == "update" else None
                )
                entity_id = self.catalog.apply_candidate_change(connection, change)
            connection.execute(text("""
                update metadata.metadata_candidates
                set status = 'promoted', promoted_at = now(),
                    rollback_payload = cast(:rollback_payload as jsonb),
                    promoted_entity_id = :entity_id
                where candidate_id = :candidate_id
            """), {
                "candidate_id": str(candidate_id), "entity_id": entity_id,
                "rollback_payload": json.dumps(previous, ensure_ascii=False, default=str)
                if previous is not None else None,
            })
        return self.get_candidate(candidate_id) or {}

    def rollback(self, candidate_id: UUID) -> dict[str, Any]:
        with self.engine.begin() as connection:
            candidate = self._locked(connection, candidate_id)
            self._require_status(candidate, "promoted")
            newer = connection.execute(text("""
                select 1 from metadata.metadata_candidates
                where supersedes = :candidate_id and status = 'promoted' limit 1
            """), {"candidate_id": str(candidate_id)}).first()
            if newer:
                raise ValueError("Rollback newer promoted versions first.")
            previous = candidate["rollback_payload"]
            kind = candidate["kind"]
            if kind == "case_correction":
                if not previous:
                    raise ValueError("Previous case gold is unavailable.")
                current = connection.execute(text("""
                    select expected_status, expected_sql, expected_query_plan, expected_result
                    from evaluation.eval_cases where case_id = :case_id for update
                """), {"case_id": candidate["entity_key"]}).mappings().first()
                promoted = candidate["payload"]
                if current is None or any(
                    current[key] != promoted.get(key)
                    for key in (
                        "expected_status", "expected_sql", "expected_query_plan",
                        "expected_result",
                    )
                ):
                    raise ValueError("Case gold changed after promotion; manual review required.")
                connection.execute(text("""
                    update evaluation.eval_cases
                    set expected_status = :status, expected_sql = :sql,
                        expected_query_plan = cast(:plan as jsonb),
                        expected_result = cast(:result as jsonb), updated_at = now()
                    where case_id = :case_id
                """), {
                    "case_id": candidate["entity_key"], "status": previous["expected_status"],
                    "sql": previous["expected_sql"],
                    "plan": json.dumps(previous["expected_query_plan"], ensure_ascii=False),
                    "result": json.dumps(previous["expected_result"], ensure_ascii=False),
                })
            else:
                current = self.catalog.candidate_previous_row(
                    connection, kind, candidate["promoted_entity_id"]
                )
                expected = {
                    key: value for key, value in candidate["payload"].items()
                    if not key.startswith("_") and key != "id"
                }
                if current is None or any(
                    current.get(key) != value for key, value in expected.items()
                ):
                    raise ValueError(
                        "Active metadata changed after promotion; manual review required."
                    )
            if kind != "case_correction" and candidate["action"] == "create":
                self.catalog.deactivate_candidate_created(
                    connection, kind, candidate["promoted_entity_id"]
                )
            elif kind != "case_correction" and previous:
                self.catalog.apply_candidate_change(connection, MetadataChangeInput(
                    kind=kind, action="update", payload=previous
                ))
            elif kind != "case_correction":
                raise ValueError("Previous metadata version is unavailable.")
            connection.execute(text("""
                update metadata.metadata_candidates
                set status = 'rolled_back', rolled_back_at = now()
                where candidate_id = :candidate_id
            """), {"candidate_id": str(candidate_id)})
        return self.get_candidate(candidate_id) or {}

    @staticmethod
    def _locked(connection: Any, candidate_id: UUID) -> dict[str, Any]:
        row = connection.execute(text("""
            select * from metadata.metadata_candidates
            where candidate_id = :candidate_id for update
        """), {"candidate_id": str(candidate_id)}).mappings().first()
        if not row:
            raise LookupError("Metadata candidate not found.")
        return dict(row)

    @staticmethod
    def _require_status(candidate: dict[str, Any], expected: str) -> None:
        if candidate["status"] != expected:
            raise ValueError(f"Candidate must be {expected}, got {candidate['status']}.")

    @staticmethod
    def _case_override(candidate: dict[str, Any]) -> dict[str, Any] | None:
        payload = candidate["payload"]
        if candidate["kind"] == "case_correction":
            return dict(payload)
        value = payload.get("_case_override")
        return dict(value) if isinstance(value, dict) else None

    @staticmethod
    def _regression_report(
        candidate: dict[str, Any], baseline: dict[str, Any], current: dict[str, Any]
    ) -> dict[str, Any]:
        candidate_id = str(candidate["candidate_id"])
        expected_manifest = {
            **dict(baseline["manifest"] or {}),
            "metadata_candidate_id": candidate_id,
            "metadata_version": str(candidate["metadata_version"]),
            "baseline_eval_run_id": str(candidate["baseline_eval_run_id"]),
        }
        override = MetadataGovernanceService._case_override(candidate)
        source_case = (
            str(override["case_id"])
            if override else candidate["payload"].get("_source_case_id")
        )
        baseline_cases = set(baseline["results"])
        current_cases = set(current["results"])
        regressions = sorted(
            case_id for case_id in baseline_cases - {source_case}
            if baseline["results"][case_id] and not current["results"].get(case_id)
        )
        source_passed = source_case is None or bool(current["results"].get(source_case))
        passed = bool(
            baseline["status"] == current["status"] == "completed"
            and baseline["variant"] == current["variant"] == "full"
            and str(current["candidate_id"]) == candidate_id
            and current["manifest"] == expected_manifest
            and baseline_cases == current_cases
            and baseline_cases
            and not regressions and source_passed
        )
        return {
            "passed": passed, "baseline_cases": len(baseline_cases),
            "candidate_cases": len(current_cases), "regressed_case_ids": regressions,
            "source_case_passed": source_passed,
        }

    @staticmethod
    def _run_results(connection: Any, run_id: UUID) -> dict[str, Any]:
        run = connection.execute(text("""
            select status, ablation_variant, comparison_manifest, metadata_candidate_id
            from evaluation.eval_runs where eval_run_id = :run_id
        """), {"run_id": str(run_id)}).mappings().first()
        rows = connection.execute(text("""
            select case_id, passed from evaluation.eval_results where eval_run_id = :run_id
        """), {"run_id": str(run_id)}).all()
        return {
            "status": run["status"] if run else None,
            "variant": run["ablation_variant"] if run else None,
            "manifest": run["comparison_manifest"] if run else None,
            "candidate_id": run["metadata_candidate_id"] if run else None,
            "results": {str(case_id): bool(passed) for case_id, passed in rows},
        }
