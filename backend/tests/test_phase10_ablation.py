from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agents.llm_result_critic import LLMResultCritic
from app.agents.llm_sql_actor import LLMSQLActor
from app.agents.llm_sql_critic import LLMSQLCritic
from app.core.config import Settings
from app.evaluation.ablation import PROFILES, comparison_manifest, get_profile
from app.evaluation.slices import case_slices, summarize_slices
from app.metadata.documents import MetadataDocument
from app.metadata.milvus_store import MilvusMetadataStore
from app.schemas.evaluation import EvaluationRunCreate
from app.schemas.query_plan import QueryPlan
from app.schemas.sql import SQLDraft
from app.services.evaluation_service import EvaluationRepository
from app.services.harness_state import HarnessState
from app.services.query_harness import QueryHarness
from app.services.query_service import QueryService
from app.services.sql_executor import SQLExecutionResult


def test_all_required_arms_are_real_distinct_switches() -> None:
    assert len(PROFILES) == 12
    assert get_profile("bm25_only").fusion_mode == "bm25"
    assert get_profile("dense_only").fusion_mode == "dense"
    assert get_profile("bm25_dense").fusion_mode == "round_robin"
    assert get_profile("bm25_dense_rrf").fusion_mode == "rrf"
    assert get_profile("no_query_plan").plan_mode == "direct"
    assert get_profile("no_critic").critic_mode == "none"
    assert get_profile("critic_conditional").critic_mode == "conditional"
    assert get_profile("full_cross_encoder").reranker
    baseline = Settings(_env_file=None, retriever_mode="legacy", enable_reranker=False)
    changed = get_profile("full").settings(baseline)
    assert changed.retriever_mode == "hybrid" and changed.enable_reranker
    assert changed.ablation_strict_retrieval
    assert baseline.retriever_mode == "legacy" and not baseline.ablation_strict_retrieval


def test_ablation_request_requires_named_group_and_known_arm() -> None:
    EvaluationRunCreate(ablation_variant="full", comparison_group="test-1")
    with pytest.raises(ValueError):
        EvaluationRunCreate(ablation_variant="full")
    with pytest.raises(ValueError):
        EvaluationRunCreate(ablation_variant="invented", comparison_group="test-1")


@pytest.mark.parametrize(
    ("existing", "expected_error"),
    [
        ({"ablation_variant": "dense_only", "comparison_manifest": {"model": "other"}},
         "different model"),
        ({"ablation_variant": "full", "comparison_manifest": {"model": "same"}},
         "already exists"),
    ],
)
def test_repository_rejects_incomparable_or_duplicate_arm(existing, expected_error) -> None:
    class Connection:
        def execute(self, statement, params):
            if "for update" in str(statement):
                return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [existing]))
            if "insert into evaluation.eval_runs" in str(statement):
                raise AssertionError("Invalid comparison must not insert a run")
            return None

    class Begin:
        def __enter__(self):
            return Connection()

        def __exit__(self, *_args):
            return None

    engine = SimpleNamespace(begin=lambda: Begin())
    repository = EvaluationRepository.__new__(EvaluationRepository)
    repository.engine = engine
    with pytest.raises(ValueError, match=expected_error):
        repository.create_run("test", "full", ablation_variant="full",
                              comparison_group="g", manifest={"model": "same"})


def test_manifest_pins_cases_model_snapshot_prompt_and_retry() -> None:
    settings = Settings(_env_file=None, llm_model="configured-model")
    cases = [{"case_id": uuid4(), "case_code": "C1", "question": "Q", "tags": []}]
    original = comparison_manifest(settings, cases, "snapshot-A", 2)
    assert original == comparison_manifest(settings, cases, "snapshot-A", 2)
    assert original["model"] == "configured-model"
    assert original["temperature"] == 0.0
    assert original != comparison_manifest(settings, cases, "snapshot-B", 2)
    assert original != comparison_manifest(settings, cases, "snapshot-A", 3)
    assert original != comparison_manifest(settings, [{**cases[0], "question": "Q2"}],
                                           "snapshot-A", 2)


def test_direct_sql_actor_does_not_receive_query_plan_or_rule_reference() -> None:
    captured = []

    class LLM:
        async def complete(self, *, messages, **kwargs):
            captured.append((messages, kwargs))
            return SimpleNamespace(
                content=json.dumps({
                    "sql": "SELECT pty_id FROM mart.ads_cust_info_d LIMIT 10",
                    "dialect": "postgres", "tables": ["ads_cust_info_d"],
                    "columns": ["pty_id"], "assumptions": [], "confidence": 0.8,
                }), model="real-model", provider="real-provider",
            )

    plan = QueryPlan(plan_status="ready", question="客户")
    result = asyncio.run(LLMSQLActor(LLM()).build(
        "客户", plan, {"table_allowlist": ["ads_cust_info_d"]}, direct_question=True
    ))
    assert result.source == "llm" and result.draft is not None
    assert result.llm_model == "real-model"
    assert "query_plan" not in captured[0][0][1].content
    assert captured[0][1]["temperature"] == 0.0


def test_direct_result_critic_prompt_uses_question_without_plan() -> None:
    critic = LLMResultCritic(None)
    draft = SQLDraft(sql="SELECT 1 LIMIT 1", dialect="postgres", tables=[], columns=[])
    messages = critic._build_messages(
        question="原问题", query_plan=QueryPlan(plan_status="ready"),
        sql_draft=draft,
        execution_result=SQLExecutionResult(
            status="success", sql=draft.sql, columns=["value"],
            rows=[{"value": 1}], row_count=1,
        ),
        hard_checks=[], metadata_context={}, preview_rows=1, direct_question=True,
    )
    assert "原问题" in messages[1].content
    assert "QueryPlan：" not in messages[1].content


def test_direct_sql_critic_prompt_uses_question_without_plan() -> None:
    draft = SQLDraft(sql="SELECT 1 LIMIT 1", dialect="postgres", tables=[], columns=[])
    messages = LLMSQLCritic._build_direct_messages("原问题", draft, [])
    assert "原问题" in messages[1].content
    assert "QueryPlan" not in messages[1].content


def test_no_query_plan_harness_skips_plan_actor_and_critic() -> None:
    calls = []

    class Service:
        ablation_profile = get_profile("no_query_plan")

        async def _emit(self, stage, status, summary, output=None):
            calls.append((stage, status))

        async def _record_trace(self, kind, payload):
            pass

        def _load_metadata_context(self, question):
            return {"source": "database"}

        def _metadata_context_summary(self, context):
            return {}

        query_plan_actor = None
        plan_critic = None

    state = HarnessState(uuid4(), 0, 2, 2)
    phase = asyncio.run(QueryHarness(Service(), state).prepare_plan("原始问题"))
    assert phase.build_result.source == "ablation_direct"
    assert phase.review_bundle.passed
    assert ("build_query_plan", "skipped") in calls


def test_no_critic_keeps_sql_hard_guardrail() -> None:
    class Critic:
        async def review(self, **kwargs):
            raise AssertionError("Critic must not be called")

    service = QueryService(
        enable_llm=False,
        settings=Settings(_env_file=None, enable_sql_explain_check=False),
        ablation_profile=get_profile("no_critic"),
    )
    service.sql_critic = Critic()
    service._build_sql_guardrail = lambda _context: SimpleNamespace(validate=lambda _sql: [])
    draft = SQLDraft(sql="SELECT 1 LIMIT 1", dialect="postgres", tables=[], columns=[])
    bundle, hard_passed, critic = asyncio.run(service._review_sql_draft(
        QueryPlan(plan_status="ready"), draft, {}
    ))
    assert hard_passed and bundle.passed and critic.status == "skipped"


def test_milvus_snapshot_validation_is_read_only_and_fails_stale_index() -> None:
    document = MetadataDocument("table:x", "table", "asset", "customer", "X", "X", (), {})
    expected_hash = document.content_hash("embedding-3")

    class Client:
        def __init__(self):
            self.rows = [{"doc_id": "table:x", "content_hash": expected_hash}]

        def has_collection(self, name):
            return True

        def load_collection(self, name):
            pass

        def query(self, **kwargs):
            return self.rows

    client = Client()
    store = MilvusMetadataStore("unused", "metadata", 1024, SimpleNamespace(),
                                "embedding-3", client=client)
    assert store.verify_synced([document])["upserted"] == 0
    client.rows = []
    with pytest.raises(RuntimeError, match="differs"):
        store.verify_synced([document])


def test_slices_are_tag_or_gold_based_and_report_own_denominators() -> None:
    row = {
        "expected_sql": "SELECT COUNT(*) FROM mart.a JOIN mart.b ON a.id=b.id",
        "expected_query_plan": {"metrics": [
            {"time_window": {"start": "20260101", "end": "20260131"}},
            {"time_window": {"start": "20260201", "end": "20260228"}},
        ]},
        "expected_status": "needs_clarification", "source_type": "official_challenge",
        "tags": ["business_term"], "passed": True,
    }
    labels = case_slices(row)
    assert {"aggregation", "multi_table_join", "multi_time_window",
            "business_terminology", "ambiguous", "challenge"} <= labels
    summary = summarize_slices([row])
    assert summary["challenge"] == {"cases": 1, "passed": 1, "accuracy": 1.0}
    assert summary["single_table"]["cases"] == 0
    assert "business_terminology" in case_slices({
        "expected_query_plan": {"filters": [{"source": "business_term"}]},
        "tags": [],
    })
