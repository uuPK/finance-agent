from __future__ import annotations

import asyncio
from uuid import uuid4

from app.schemas.v2_protocol import FailureEvent, HarnessAction
from app.services.failure_router import FailureRouter
from app.services.harness_state import HarnessState
from app.services.query_harness import QueryHarness
from app.services.query_service import QueryService


def test_failure_router_maps_only_explicitly_supported_failure_domains() -> None:
    router = FailureRouter()
    cases = [
        (
            FailureEvent(stage="plan", error_type="wrong_grain", retryable=True),
            HarnessAction.PLAN_REPAIR,
        ),
        (
            FailureEvent(stage="sql", error_type="missing_time_filter", retryable=True),
            HarnessAction.SQL_REPAIR,
        ),
        (
            FailureEvent(stage="execution", error_type="sql_syntax_error", retryable=True),
            HarnessAction.SQL_REPAIR,
        ),
        (
            FailureEvent(stage="execution", error_type="column_not_found", retryable=True),
            HarnessAction.TERMINATE,
        ),
        (
            FailureEvent(stage="execution", error_type="timeout", retryable=True),
            HarnessAction.TERMINATE,
        ),
        (
            FailureEvent(stage="retrieval", error_type="missing_context", retryable=True),
            HarnessAction.CONTEXT_REFRESH,
        ),
        (
            FailureEvent(stage="plan", error_type="invalid_plan", retryable=False),
            HarnessAction.TERMINATE,
        ),
    ]

    for failure, expected in cases:
        assert router.propose(failure) == expected


def test_harness_records_final_route_and_exhausted_budget_without_failure_text() -> None:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    # Exercise routing policy only; no model actor is called by this test.
    service.llm_enabled = True
    state = HarnessState(uuid4(), 0, max_plan_repairs=0, max_sql_repairs=0)
    service.harness_state = state
    harness = QueryHarness(service, state)
    failure = FailureEvent(
        stage="plan",
        error_type="wrong_grain",
        evidence=["sensitive evidence text"],
        repair_hint="private repair hint",
        retryable=True,
    )

    decision = asyncio.run(
        harness.route_failure(
            failure,
            source_stage="query_plan_hard_review",
            source_attempt=0,
        )
    )

    assert decision.candidate_action == HarnessAction.PLAN_REPAIR
    assert decision.final_action == HarnessAction.TERMINATE
    assert decision.reason_code == "budget_exhausted"
    assert state.plan_repairs_used == 0
    assert state.route_count == 1
    assert [event["type"] for event in events] == [
        "route.decided",
        "budget.exhausted",
        "route.executed",
    ]
    route_output = events[0]["output"]
    assert route_output["candidate_action"] == "PLAN_REPAIR"
    assert route_output["final_action"] == "TERMINATE"
    assert route_output["budget"] == {
        "domain": "plan",
        "used": 0,
        "limit": 0,
        "exhausted": True,
        "reserved": False,
    }
    assert "sensitive evidence text" not in str(events)
    assert "private repair hint" not in str(events)


def test_unimplemented_context_refresh_is_audited_then_terminated() -> None:
    events: list[dict] = []

    async def sink(event: dict) -> None:
        events.append(event)

    service = QueryService(enable_llm=False, event_sink=sink)
    service.llm_enabled = True
    state = HarnessState(uuid4(), 0, max_plan_repairs=1, max_sql_repairs=1)
    service.harness_state = state
    harness = QueryHarness(service, state)
    decision = asyncio.run(
        harness.route_failure(
            FailureEvent(stage="sql", error_type="missing_metadata_context", retryable=True),
            source_stage="sql_hard_review",
            source_attempt=0,
        )
    )

    assert decision.candidate_action == HarnessAction.CONTEXT_REFRESH
    assert decision.final_action == HarnessAction.TERMINATE
    assert decision.reason_code == "action_not_implemented"
    assert state.sql_repairs_used == 0
    assert [event["type"] for event in events] == ["route.decided", "route.executed"]
    assert events[0]["output"]["candidate_action"] == "CONTEXT_REFRESH"
    assert events[0]["output"]["final_action"] == "TERMINATE"
