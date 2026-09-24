from __future__ import annotations

import asyncio
from uuid import uuid4

from app.schemas.query_plan import QueryMetric, QueryPlan
from app.schemas.review import ReviewDecision
from app.schemas.v2_protocol import EvidenceRef
from app.services.trace_facts import context_facts, plan_facts, validation_facts
from app.services.trace_recorder import TraceRecorder


def test_stage_span_and_child_telemetry_share_parent_and_monotonic_duration() -> None:
    events: list[dict] = []
    ticks = iter([10.0, 10.275])

    async def sink(event: dict) -> None:
        events.append(event)

    recorder = TraceRecorder(sink, clarification_round=2, clock=lambda: next(ticks))
    asyncio.run(recorder.emit_stage("retrieve_metadata", "running", "start", stage_attempt=1))
    asyncio.run(recorder.record("context_selection", {"selected_item_ids": ["metric:x"]}))
    asyncio.run(recorder.emit_stage("retrieve_metadata", "passed", "done", stage_attempt=1))

    started, child, finished = events
    assert started["span_id"] == finished["span_id"]
    assert child["parent_span_id"] == started["span_id"]
    assert finished["duration_ms"] == 275
    assert started["duration_ms"] is None
    assert [(event["clarification_round"], event["stage_attempt"]) for event in events] == [
        (2, 1),
        (2, 1),
        (2, 1),
    ]
    assert [event["attempt"] for event in events] == [3, 3, 3]


def test_telemetry_failure_is_marked_without_repeating_record() -> None:
    events: list[dict] = []
    trace_calls = 0

    async def sink(event: dict) -> None:
        nonlocal trace_calls
        if event["type"].startswith("trace."):
            trace_calls += 1
            raise RuntimeError("telemetry database unavailable")
        events.append(event)

    recorder = TraceRecorder(sink)
    asyncio.run(recorder.record("context_selection", {"selected_item_ids": []}))
    assert trace_calls == 1
    assert recorder.telemetry_write_failures == 1
    asyncio.run(recorder.emit_stage("retrieve_metadata", "passed", "done"))
    assert events[0]["output"]["trace_warning"]["telemetry_write_failures"] == 1
    assert recorder.telemetry_write_failures == 0


def test_interrupted_stage_is_closed_with_error_type_only() -> None:
    events: list[dict] = []
    ticks = iter([3.0, 3.05])

    async def sink(event: dict) -> None:
        events.append(event)

    recorder = TraceRecorder(sink, clock=lambda: next(ticks))
    asyncio.run(recorder.emit_stage("execute_sql", "running", "start"))
    asyncio.run(recorder.close_open_spans("RuntimeError"))
    assert len(events) == 2
    assert events[1]["span_id"] == events[0]["span_id"]
    assert events[1]["status"] == "failed"
    assert 49 <= events[1]["duration_ms"] <= 50
    assert events[1]["output"] == {"error_type": "RuntimeError"}


def test_trace_fact_projections_exclude_source_text_values_and_result_rows() -> None:
    context = {
        "source": "database",
        "retrieval": {"strategy": "milvus_bm25_dense_rrf_rerank"},
        "retrieval_trace": [
            {
                "doc_id": "metric:total_asset",
                "bm25_rank": 1,
                "dense_rank": 2,
                "rrf_score": 0.03,
                "selected_reason": "bm25+dense -> RRF -> rerank",
                "body": "private metadata body",
            }
        ],
        "context_bundle": {"item_ids": ["metric:total_asset"]},
        "context_stats": {"context_tokens": 123, "budget": 200},
    }
    context_payload = context_facts(context)
    assert context_payload["evidence"][0]["selected_reason"] == "bm25_dense_rrf_rerank"
    assert context_payload["context_tokens_estimated"] == 123
    assert "private metadata body" not in str(context_payload)

    plan = QueryPlan(
        metrics=[
            QueryMetric(
                name="资产",
                metric_code="total_asset",
                provenance=[
                    EvidenceRef(
                        source_type="metadata_definition",
                        source_id="metric:total_asset",
                        source_text="private definition",
                    )
                ],
            )
        ]
    )
    plan_payload = plan_facts(plan)
    assert plan_payload["evidence_items"][0]["evidence"][0]["source_id"] == "metric:total_asset"
    assert "private definition" not in str(plan_payload)

    validation = ReviewDecision(
        passed=False,
        score=30,
        stage="sql_review",
        error_type="unsafe_column",
        reason="private SQL and row value",
        evidence=[str(uuid4())],
        confidence=0.9,
    )
    validation_payload = validation_facts([validation])
    assert validation_payload["checks"][0]["error_type"] == "unsafe_column"
    assert "private SQL and row value" not in str(validation_payload)
