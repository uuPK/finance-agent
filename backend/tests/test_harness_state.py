from __future__ import annotations

from uuid import uuid4

import pytest

from app.services.harness_state import HarnessState


def test_plan_and_sql_repair_budgets_are_independent_and_cannot_overrun() -> None:
    state = HarnessState(uuid4(), clarification_round=1, max_plan_repairs=2, max_sql_repairs=1)
    assert state.reserve_repair("plan") == 1
    assert state.reserve_repair("plan") == 2
    assert not state.can_repair("plan")
    assert state.can_repair("sql")
    with pytest.raises(RuntimeError, match="plan repair budget exhausted"):
        state.reserve_repair("plan")
    assert state.reserve_repair("sql") == 1
    assert state.total_retries == 3
    assert state.budget_facts("sql") == {"domain": "sql", "used": 1, "limit": 1, "exhausted": True}
    with pytest.raises(RuntimeError, match="sql repair budget exhausted"):
        state.reserve_repair("sql")
    assert state.total_retries == 3


def test_stage_ledger_uses_trace_span_and_only_reference_ids() -> None:
    state = HarnessState(uuid4(), clarification_round=1, max_plan_repairs=2, max_sql_repairs=2)
    span_id = uuid4()
    stage = {
        "type": "stage.started",
        "stage": "build_query_plan",
        "status": "running",
        "clarification_round": 1,
        "stage_attempt": 0,
        "span_id": span_id,
        "parent_span_id": None,
        "duration_ms": None,
    }
    state.observe_stage(stage)
    state.observe_telemetry(
        {
            "type": "trace.context_selection",
            "stage": "build_query_plan",
            "stage_attempt": 0,
            "output": {
                "selected_item_ids": ["metric:total_asset"],
                "context_tokens_estimated": 140,
                "retrieval_calls": 2,
                "raw_prompt": "must not be copied",
            },
        }
    )
    state.observe_telemetry(
        {
            "type": "trace.plan_evidence",
            "stage": "build_query_plan",
            "stage_attempt": 0,
            "output": {
                "evidence_items": [
                    {
                        "metadata_ref_id": "metric:total_asset",
                        "evidence": [{"source_id": "table:mart.assets", "source_text": "private"}],
                    }
                ]
            },
        }
    )
    state.observe_telemetry(
        {
            "type": "trace.llm_call",
            "stage": "build_query_plan",
            "stage_attempt": 0,
            "output": {"prompt_tokens": 21, "completion_tokens": 9},
        }
    )
    state.observe_stage(
        {**stage, "type": "stage.completed", "status": "passed", "duration_ms": 480}
    )
    record = state.stages[("build_query_plan", 0)]
    assert record.span_id == span_id
    assert record.status == "passed"
    assert record.duration_ms == 480
    assert record.input_refs == {"metric:total_asset"}
    assert record.output_refs == {"metric:total_asset", "table:mart.assets"}
    assert state.prompt_tokens == 21
    assert state.completion_tokens == 9
    assert state.context_tokens_estimated == 140
    assert state.retrieval_calls == 2
    assert "must not be copied" not in str(state)
    assert "private" not in str(state)


def test_missing_model_usage_stays_unknown_and_wrong_round_is_rejected() -> None:
    state = HarnessState(uuid4(), clarification_round=0, max_plan_repairs=0, max_sql_repairs=0)
    state.observe_telemetry(
        {
            "type": "trace.llm_call",
            "stage": "build_query_plan",
            "stage_attempt": 0,
            "output": {"prompt_tokens": None, "completion_tokens": None},
        }
    )
    assert state.llm_calls == 1
    assert state.prompt_tokens is None
    assert state.completion_tokens is None
    with pytest.raises(ValueError, match="another clarification round"):
        state.observe_stage(
            {
                "type": "stage.started",
                "stage": "build_query_plan",
                "status": "running",
                "clarification_round": 1,
                "stage_attempt": 0,
            }
        )
