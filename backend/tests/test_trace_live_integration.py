"""Opt-in real-provider smoke test; keeps response and event data in memory only."""

from __future__ import annotations

import asyncio
import os

import pytest

from app.core.config import get_settings
from app.schemas.query import QueryRequest
from app.services.query_service import QueryService

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_TRACE_LIVE_TESTS") != "1",
    reason="requires explicit opt-in, real PostgreSQL/Milvus, and configured model APIs",
)


class _MemoryOnlyAudit:
    def start_query_run(self, **_kwargs: object) -> None:
        pass

    def finish_query_run(self, **_kwargs: object) -> None:
        pass

    def log_sql_execution(self, **_kwargs: object) -> None:
        return None

    def log_result_validation(self, **_kwargs: object) -> None:
        pass


def test_real_model_and_hybrid_retrieval_emit_trace_without_saving_results() -> None:
    settings = get_settings()
    assert settings.active_llm_api_key
    assert settings.zhipu_retrieval_api_key or settings.zhipu_api_key
    assert settings.retriever_mode == "hybrid"

    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(event_sink=sink, audit_logger=_MemoryOnlyAudit())
    response = asyncio.run(
        service.run(
            QueryRequest(question="统计客户总数", user_id="trace-live-smoke"),
            start_audit=False,
        )
    )
    context_events = [event for event in events if event["type"] == "trace.context_selection"]
    assert context_events
    assert any(
        str(event["output"].get("strategy", "")).startswith("milvus_bm25_dense_rrf")
        for event in context_events
    )
    model_events = [event for event in events if event["type"] == "trace.llm_call"]
    assert model_events
    assert any(
        event["output"].get("usage_source") == "provider_response"
        and isinstance(event["output"].get("prompt_tokens"), int)
        and event["output"]["prompt_tokens"] > 0
        for event in model_events
    )
    assert any(
        event["duration_ms"] is not None
        for event in events
        if event["stage"] == "retrieve_metadata"
        and event["status"] != "running"
        and not event["type"].startswith("trace.")
    )
    assert response.status in {"completed", "needs_clarification", "failed"}
    # No response, SQL text, prompt, or rows are written to a file or database here.
    for event in events:
        if event["type"].startswith("trace."):
            assert "result_preview" not in event["output"]
            assert "sql" not in event["output"]
            assert "messages" not in event["output"]
