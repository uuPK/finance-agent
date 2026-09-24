"""Bounded, reference-only projections for Phase 5.1 trace telemetry."""

from __future__ import annotations

import re
from typing import Any

from app.schemas.query_plan import QueryPlan
from app.schemas.review import ReviewDecision

_CODE = re.compile(r"^[A-Za-z][A-Za-z0-9_:.\-/]{0,127}$")
_REASONS = {
    "bm25 -> RRF": "bm25_rrf",
    "dense -> RRF": "dense_rrf",
    "bm25+dense -> RRF": "bm25_dense_rrf",
    "bm25 -> RRF -> rerank": "bm25_rrf_rerank",
    "dense -> RRF -> rerank": "dense_rrf_rerank",
    "bm25+dense -> RRF -> rerank": "bm25_dense_rrf_rerank",
    "query_domain_anchor": "query_domain_anchor",
    "query_plan_anchor": "query_plan_anchor",
    "metric_source_table": "metric_source_table",
    "metric_formula_table": "metric_formula_table",
    "metric_formula_column": "metric_formula_column",
    "column_parent_table": "column_parent_table",
    "join_endpoint": "join_endpoint",
    "join_path_closure": "join_path_closure",
    "targeted_legacy": "targeted_legacy",
}


def _code(value: Any) -> str | None:
    return value if isinstance(value, str) and _CODE.fullmatch(value) else None


def context_facts(context: dict[str, Any]) -> dict[str, Any]:
    """Ranks, chosen IDs, and budget accounting without metadata body text."""
    retrieval = context.get("retrieval")
    retrieval = retrieval if isinstance(retrieval, dict) else {}
    stats = context.get("context_stats")
    stats = stats if isinstance(stats, dict) else {}
    bundle = context.get("context_bundle")
    bundle = bundle if isinstance(bundle, dict) else {}
    evidence = context.get("retrieval_trace") or retrieval.get("evidence") or []
    evidence = evidence if isinstance(evidence, list) else []
    item_ids = bundle.get("item_ids") or []
    item_ids = item_ids if isinstance(item_ids, list) else []
    safe_evidence = []
    for item in evidence[:64]:
        if not isinstance(item, dict):
            continue
        doc_id = _code(item.get("doc_id"))
        if doc_id is None:
            continue
        reason = item.get("selected_reason")
        safe_evidence.append(
            {
                "doc_id": doc_id,
                "bm25_rank": item.get("bm25_rank"),
                "dense_rank": item.get("dense_rank"),
                "rrf_score": item.get("rrf_score"),
                "reranker_score": item.get("reranker_score"),
                "selected_reason": _REASONS.get(reason) if isinstance(reason, str) else None,
            }
        )
    return {
        "strategy": _code(retrieval.get("strategy")),
        "source": _code(context.get("source")),
        "evidence_count": len(evidence),
        "evidence": safe_evidence,
        "selected_item_count": len(item_ids),
        "selected_item_ids": [item_id for item_id in item_ids[:128] if _code(item_id)],
        "context_tokens_estimated": stats.get("context_tokens"),
        "context_budget": stats.get("budget"),
        "dedup_count": stats.get("dedup_count"),
        "eviction_count": stats.get("eviction_count"),
        "compaction_count": stats.get("compaction_count"),
        "retrieval_calls": stats.get("retrieval_calls"),
    }


def plan_facts(plan: QueryPlan) -> dict[str, Any]:
    """Plan evidence identifiers, never question, filter values, or source text."""
    items: list[dict[str, Any]] = []
    groups = (
        ("metric", plan.metrics),
        ("dimension", plan.dimensions),
        ("filter", plan.filters),
        ("assumption", plan.assumptions),
    )
    for kind, group in groups:
        for item in group:
            reference = getattr(item, "metadata_ref", None)
            sources = getattr(item, "provenance", None) or []
            items.append(
                {
                    "kind": kind,
                    "code": _code(
                        getattr(item, "metric_code", None)
                        or getattr(item, "dimension_code", None)
                        or getattr(item, "field_code", None)
                    ),
                    "metadata_ref_id": _code(reference.ref_id) if reference else None,
                    "evidence": [
                        {
                            "source_type": source.source_type,
                            "source_id": _code(source.source_id),
                            "confidence": source.confidence,
                        }
                        for source in sources[:8]
                    ],
                }
            )
    if plan.time_range is not None:
        items.append(
            {
                "kind": "time_range",
                "code": None,
                "metadata_ref_id": None,
                "evidence": [
                    {
                        "source_type": source.source_type,
                        "source_id": _code(source.source_id),
                        "confidence": source.confidence,
                    }
                    for source in (plan.time_range.provenance or [])[:8]
                ],
            }
        )
    return {
        "plan_status": plan.plan_status,
        "intent": plan.intent,
        "evidence_item_count": len(items),
        "evidence_items": items[:64],
    }


def validation_facts(checks: list[ReviewDecision]) -> dict[str, Any]:
    """Decision codes and scores only; no free-text rationale or SQL."""
    return {
        "check_count": len(checks),
        "passed": all(check.passed for check in checks),
        "checks": [
            {
                "stage": check.stage,
                "passed": check.passed,
                "error_type": _code(check.error_type),
                "score": check.score,
                "confidence": check.confidence,
            }
            for check in checks[:64]
        ],
    }
