import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api import run_routes
from app.main import app
from app.schemas.query import QueryRequest
from app.schemas.run import QueryEvent, QueryRunSnapshot
from app.services.query_service import QueryService
from app.services.run_repository import sanitize_event_payload


class StaticSchemaContextProvider:
    def load(self, query_plan=None, question=None) -> dict:
        return {
            "source": "database",
            "table_count": 1,
            "metric_count": 0,
            "tables": [],
            "metrics": [],
            "business_terms": [],
            "join_relationships": [],
            "question_examples": [],
            "table_allowlist": ["customer_info"],
            "sensitive_columns": ["phone"],
            "allowed_columns_by_table": {"customer_info": ["customer_id"]},
        }


class NoopAuditLogger:
    def start_query_run(self, *args, **kwargs) -> None:
        return None

    def finish_query_run(self, *args, **kwargs) -> None:
        return None


def test_event_payload_redacts_secrets_and_sensitive_fields() -> None:
    payload = sanitize_event_payload(
        {
            "api_key": "secret",
            "authorization": "Bearer token-value",
            "phone": "13800000000",
            "message": "failed at postgresql://user:password@localhost/db",
            "safe": "customer_info",
        }
    )

    assert payload["api_key"] == "[REDACTED]"
    assert payload["authorization"] == "[REDACTED]"
    assert payload["phone"] == "[REDACTED]"
    assert payload["message"] == "failed at [REDACTED_DATABASE_URL]"
    assert payload["safe"] == "customer_info"


def test_query_service_emits_stage_events_in_order() -> None:
    events: list[dict] = []

    async def collect(event: dict) -> None:
        events.append(event)

    response = asyncio.run(
        QueryService(
            enable_llm=False,
            schema_context_provider=StaticSchemaContextProvider(),
            audit_logger=NoopAuditLogger(),
            event_sink=collect,
        ).run(QueryRequest(question="找出高净值客户"))
    )

    assert response.status == "needs_clarification"
    assert [event["stage"] for event in events[:3]] == [
        "receive_question",
        "retrieve_metadata",
        "retrieve_metadata",
    ]
    assert any(event["stage"] == "build_query_plan" for event in events)
    assert any(event["stage"] == "query_plan_hard_review" for event in events)
    assert all(
        event["type"] in {"stage.started", "stage.completed", "stage.failed"} for event in events
    )


def test_sse_replays_only_events_after_cursor(monkeypatch) -> None:
    query_id = uuid4()
    now = datetime.now(UTC)
    terminal = QueryEvent(
        event_id=2,
        query_id=query_id,
        type="run.completed",
        stage="final_response",
        status="passed",
        summary="查询已完成",
        occurred_at=now,
    )
    snapshot = QueryRunSnapshot(
        query_id=query_id,
        user_id="client",
        question="客户数量",
        status="completed",
        created_at=now,
        updated_at=now,
    )

    class FakeRepository:
        def get_run(self, requested_id, include_events=True):
            return snapshot if requested_id == query_id else None

        def list_events(self, requested_id, after=0):
            return [terminal] if requested_id == query_id and after < 2 else []

    monkeypatch.setattr(
        run_routes,
        "get_run_manager",
        lambda: SimpleNamespace(repository=FakeRepository()),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/chat/runs/{query_id}/events",
            headers={"Last-Event-ID": "1"},
        )

    assert response.status_code == 200
    assert "id: 2" in response.text
    assert "event: run.completed" in response.text
    assert '"event_id":2' in response.text
