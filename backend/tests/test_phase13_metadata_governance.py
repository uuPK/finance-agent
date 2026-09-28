"""Phase 13 governance gates; tests never call the real model or save eval runs."""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.db.session import engine
from app.metadata.candidate_overlay import overlay_rows
from app.metadata.documents import MetadataDocument
from app.metadata.hybrid_retriever import HybridMetadataRetriever
from app.schemas.evaluation import ReviewDecisionInput
from app.schemas.metadata import MetadataChangeInput
from app.services.metadata_governance import MetadataGovernanceService


def test_candidate_overlay_does_not_mutate_production_rows() -> None:
    rows = {"business_term": [{"term": "old", "definition": "original"}]}
    candidate = {
        "candidate_id": uuid4(), "kind": "term", "action": "update",
        "payload": {
            "term": "old", "definition": "candidate",
            "_source_case_id": "hidden-gold",
        },
    }

    overlaid = overlay_rows({key: list(value) for key, value in rows.items()}, candidate)

    assert overlaid["business_term"] == [{"term": "old", "definition": "candidate"}]
    assert rows["business_term"] == [{"term": "old", "definition": "original"}]


def test_candidate_reranker_failure_does_not_silently_degrade(monkeypatch) -> None:
    document = MetadataDocument(
        "table:mart.customer", "table", "customer", "customer",
        "customer", "customer", metadata={"table_name": "customer"},
    )
    monkeypatch.setattr(
        "app.metadata.hybrid_retriever.load_metadata_documents",
        lambda *_: [document],
    )
    store = SimpleNamespace(
        sync=lambda _: {"total": 1, "upserted": 0, "deleted": 0},
        search_bm25=lambda *_: [document.doc_id],
        search_dense=lambda *_: [document.doc_id],
    )
    reranker = SimpleNamespace(rerank=lambda *_: (_ for _ in ()).throw(RuntimeError("down")))
    settings = Settings(_env_file=None, enable_reranker=True)
    retriever = HybridMetadataRetriever(
        Mock(), settings, store, reranker,
        candidate={"kind": "term", "candidate_id": uuid4(), "payload": {}},
    )

    with pytest.raises(RuntimeError, match="down"):
        retriever.retrieve("customer")


def test_regression_requires_same_cases_manifest_and_no_non_source_regression() -> None:
    governance = MetadataGovernanceService()
    candidate_id = uuid4()
    baseline_id = uuid4()
    manifest = {"database_sha256": "fixed"}
    candidate = {
        "candidate_id": candidate_id, "metadata_version": uuid4(),
        "baseline_eval_run_id": baseline_id,
        "kind": "case_correction", "payload": {"case_id": "source"},
    }
    baseline = {
        "status": "completed", "variant": "full", "manifest": manifest,
        "candidate_id": None, "results": {"other": True, "source": False},
    }
    current = {
        "status": "completed", "variant": "full", "candidate_id": candidate_id,
        "manifest": {
            **manifest, "metadata_candidate_id": str(candidate_id),
            "metadata_version": str(candidate["metadata_version"]),
            "baseline_eval_run_id": str(baseline_id),
        },
        "results": {"other": True, "source": True},
    }

    assert governance._regression_report(candidate, baseline, current)["passed"] is True
    current["results"]["other"] = False
    assert governance._regression_report(candidate, baseline, current)["passed"] is False
    current["results"]["other"] = True
    current["manifest"]["database_sha256"] = "changed"
    assert governance._regression_report(candidate, baseline, current)["passed"] is False


def test_unapproved_candidate_cannot_promote_or_rollback(monkeypatch) -> None:
    class EmptyEngine:
        @contextmanager
        def begin(self):
            yield object()

    governance = MetadataGovernanceService(EmptyEngine())
    monkeypatch.setattr(
        governance, "_locked",
        lambda *_: {"status": "candidate", "reviewer_id": "reviewer"},
    )
    with pytest.raises(ValueError, match="must be ready"):
        governance.promote(uuid4())
    with pytest.raises(ValueError, match="must be promoted"):
        governance.rollback(uuid4())
    with pytest.raises(ValueError, match="different person"):
        governance.approve(uuid4(), "reviewer")


def test_review_staging_is_transactional_and_does_not_activate_term() -> None:
    try:
        with engine.connect() as connection:
            review_id = connection.execute(text(
                "select review_item_id from evaluation.review_items limit 1"
            )).scalar_one_or_none()
            if review_id is None:
                pytest.skip("No existing review item for transactional staging test.")
            term = f"phase13_staging_{uuid4().hex}"
            transaction = connection.begin_nested()
            try:
                decision = ReviewDecisionInput(
                    review_item_id=review_id,
                    reviewer_id="phase13_test_reviewer",
                    verdict="incorrect",
                    metadata_changes=[MetadataChangeInput(
                        kind="term", action="create",
                        payload={"term": term, "definition": "temporary test candidate"},
                    )],
                )
                count = MetadataGovernanceService(engine).stage_review_decision(
                    connection,
                    {"review_item_id": review_id, "source_query_id": None, "case_id": None},
                    decision,
                )
                assert count == 1
                assert connection.execute(text(
                    "select count(*) from metadata.metadata_candidates "
                    "where source_review_item_id = :review_id and entity_key = :term"
                ), {"review_id": str(review_id), "term": term}).scalar_one() == 1
                assert connection.execute(text(
                    "select count(*) from metadata.business_terms where term = :term"
                ), {"term": term}).scalar_one() == 0
            finally:
                transaction.rollback()
    except SQLAlchemyError as exc:
        pytest.skip(f"PostgreSQL unavailable for integration check: {type(exc).__name__}")
