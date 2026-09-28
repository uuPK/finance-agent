"""Local, rollback-only contracts across the backend's governance boundaries."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import text

from app.db.session import engine
from app.metadata.schema_context import SchemaContextProvider
from app.schemas.evaluation import ReviewDecisionInput
from app.schemas.metadata import MetadataChangeInput
from app.services.metadata_governance import MetadataGovernanceService


@pytest.mark.skipif(os.getenv("RUN_TRACE_DB_TESTS") != "1", reason="requires local PostgreSQL")
def test_review_sql_uses_full_physical_policy_not_question_retrieval() -> None:
    policy = SchemaContextProvider().load_review_sql_policy()

    assert policy["source"] == "database"
    assert "dws_cust_aset_d" in policy["table_allowlist"]
    assert "pty_id" in policy["allowed_columns_by_table"]["dws_cust_aset_d"]
    MetadataGovernanceService()._validate_reference_sql(
        "select a.pty_id from mart.dws_cust_aset_d a limit 1"
    )
    sensitive_name = "name"
    assert sensitive_name in policy["sensitive_columns"]
    sensitive_table = next(
        table
        for table, names in policy["allowed_columns_by_table"].items()
        if sensitive_name in names
    )
    with pytest.raises(ValueError, match="guardrail"):
        MetadataGovernanceService()._validate_reference_sql(
            f"select a.{sensitive_name} from mart.{sensitive_table} a limit 1"
        )
    with pytest.raises(ValueError, match="guardrail"):
        MetadataGovernanceService()._validate_reference_sql(
            "select a.pty_id from mart.dws_cust_aset_d a; delete from mart.dws_cust_aset_d"
        )


@pytest.mark.skipif(os.getenv("RUN_TRACE_DB_TESTS") != "1", reason="requires local PostgreSQL")
def test_clarification_candidate_preserves_existing_gold_result() -> None:
    with engine.connect() as connection:
        outer = connection.begin()
        try:
            case = (
                connection.execute(
                    text("""
                select case_id, expected_result from evaluation.eval_cases
                where is_active = true and expected_result <> '{}'::jsonb
                limit 1
            """)
                )
                .mappings()
                .first()
            )
            review_id = connection.execute(
                text("select review_item_id from evaluation.review_items limit 1")
            ).scalar_one_or_none()
            if case is None or review_id is None:
                pytest.skip("Local evaluation/review fixtures are unavailable.")
            decision = ReviewDecisionInput(
                review_item_id=review_id,
                reviewer_id="clarification_reviewer",
                verdict="needs_clarification",
                corrected_query_plan={"clarifications": [{"field": "date"}]},
            )
            count = MetadataGovernanceService().stage_review_decision(
                connection,
                {
                    "case_id": case["case_id"],
                    "review_item_id": review_id,
                    "source_query_id": None,
                },
                decision,
            )
            assert count == 1
            payload = connection.execute(
                text("""
                select payload from metadata.metadata_candidates
                where source_review_item_id = :review_id and kind = 'case_correction'
                  and reviewer_id = :reviewer
                order by created_at desc limit 1
            """),
                {
                    "review_id": str(review_id),
                    "reviewer": "clarification_reviewer",
                },
            ).scalar_one()
            assert payload["expected_result"] == case["expected_result"]
            assert (
                connection.execute(
                    text("""
                select expected_result from evaluation.eval_cases where case_id = :case_id
            """),
                    {"case_id": str(case["case_id"])},
                ).scalar_one()
                == case["expected_result"]
            )
        finally:
            outer.rollback()


@pytest.mark.skipif(os.getenv("RUN_TRACE_DB_TESTS") != "1", reason="requires local PostgreSQL")
@pytest.mark.parametrize("action", ["create", "update"])
def test_candidate_approval_regression_promotion_and_rollback_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    """Prove the advertised lifecycle with real SQL, without persisting test records."""
    with engine.connect() as connection:
        outer = connection.begin()

        class TransactionBoundEngine:
            @contextmanager
            def begin(self):
                nested = connection.begin_nested()
                try:
                    yield connection
                    nested.commit()
                except Exception:
                    nested.rollback()
                    raise

            @contextmanager
            def connect(self):
                yield connection

        try:
            review_id = connection.execute(
                text("select review_item_id from evaluation.review_items limit 1")
            ).scalar_one_or_none()
            case_id = connection.execute(
                text("select case_id from evaluation.eval_cases where is_active limit 1")
            ).scalar_one_or_none()
            if review_id is None or case_id is None:
                pytest.skip("Local review/case fixtures are unavailable.")
            governance = MetadataGovernanceService(TransactionBoundEngine())
            term = f"phase13_lifecycle_{uuid4().hex}"
            if action == "update":
                connection.execute(
                    text("""
                    insert into metadata.business_terms (term, definition, is_active)
                    values (:term, 'original', true)
                """),
                    {"term": term},
                )
            decision = ReviewDecisionInput(
                review_item_id=review_id,
                reviewer_id="original_reviewer",
                verdict="incorrect",
                metadata_changes=[
                    MetadataChangeInput(
                        kind="term",
                        action=action,
                        payload={"term": term, "definition": "temporary"},
                    )
                ],
            )
            assert (
                governance.stage_review_decision(
                    connection,
                    {
                        "review_item_id": review_id,
                        "source_query_id": None,
                        "case_id": None,
                    },
                    decision,
                )
                == 1
            )
            candidate = (
                connection.execute(
                    text(
                        "select candidate_id, metadata_version from metadata.metadata_candidates "
                        "where source_review_item_id = :review_id and entity_key = :term"
                    ),
                    {"review_id": str(review_id), "term": term},
                )
                .mappings()
                .one()
            )
            candidate_id = candidate["candidate_id"]
            assert (
                connection.execute(
                    text("select count(*) from metadata.business_terms where term = :term"),
                    {"term": term},
                ).scalar_one()
                == (1 if action == "update" else 0)
            )

            with pytest.raises(ValueError, match="different person"):
                governance.approve(candidate_id, "original_reviewer")
            assert governance.approve(candidate_id, "second_reviewer")["status"] == "approved"

            baseline_id, run_id = uuid4(), uuid4()
            manifest = {"database_sha256": "transaction-test-snapshot"}
            candidate_manifest = {
                **manifest,
                "metadata_candidate_id": str(candidate_id),
                "metadata_version": str(candidate["metadata_version"]),
                "baseline_eval_run_id": str(baseline_id),
            }
            for eval_run_id, run_manifest, linked_candidate in (
                (baseline_id, manifest, None),
                (run_id, candidate_manifest, candidate_id),
            ):
                connection.execute(
                    text("""
                    insert into evaluation.eval_runs
                        (eval_run_id, run_name, status, ablation_variant,
                         comparison_manifest, metadata_candidate_id)
                    values (:run_id, 'rollback-only governance test', 'completed', 'full',
                            cast(:manifest as jsonb), :candidate_id)
                """),
                    {
                        "run_id": str(eval_run_id),
                        "manifest": json.dumps(run_manifest),
                        "candidate_id": str(linked_candidate) if linked_candidate else None,
                    },
                )
                connection.execute(
                    text("""
                    insert into evaluation.eval_results (eval_run_id, case_id, passed)
                    values (:run_id, :case_id, true)
                """),
                    {"run_id": str(eval_run_id), "case_id": str(case_id)},
                )

            governance.begin_regression(candidate_id, baseline_id, run_id)
            assert governance.finish_regression(candidate_id)["status"] == "ready"
            monkeypatch.setattr(
                "app.services.metadata_governance.database_fingerprint",
                lambda _engine: "transaction-test-snapshot",
            )
            assert governance.promote(candidate_id)["status"] == "promoted"
            assert (
                connection.execute(
                    text("select definition from metadata.business_terms where term = :term"),
                    {"term": term},
                ).scalar_one()
                == "temporary"
            )
            assert governance.rollback(candidate_id)["status"] == "rolled_back"
            row = connection.execute(
                text(
                    "select is_active, definition from metadata.business_terms where term = :term"
                ),
                {"term": term},
            ).mappings().one()
            assert row["is_active"] is (action == "update")
            assert row["definition"] == ("original" if action == "update" else "temporary")
        finally:
            outer.rollback()
