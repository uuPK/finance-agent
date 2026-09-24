from app.agents.llm_plan_critic import LLMPlanCritic
from app.agents.llm_query_plan_actor import LLMQueryPlanActor
from app.agents.plan_reviewer import QueryPlanHardValidator
from app.guardrails.plan_grounding import ground_query_plan
from app.schemas.query_plan import (
    BusinessEntity,
    ClarificationQuestion,
    DataRequirement,
    QueryDimension,
    QueryFilter,
    QueryMetric,
    QueryPlan,
    QueryValue,
    TimeRange,
)
from app.schemas.review import ReviewDecision
from app.schemas.v2_protocol import EvidenceRef
from app.services.query_service import QueryService


def _plan(*, value: int = 1_000_000, code: str = "total_asset") -> QueryPlan:
    return QueryPlan(
        plan_status="ready",
        intent="customer_segmentation",
        question="untrusted plan question",
        subject=BusinessEntity(name="客户", entity_type="customer", is_resolved=True),
        metrics=[QueryMetric(name="客户数量", metric_code="customer_count")],
        filters=[
            QueryFilter(
                term="总资产",
                operator=">=",
                metric_code=code,
                value=QueryValue(raw=value, normalized=value, value_type="number"),
                is_resolved=True,
            )
        ],
        data_requirements=DataRequirement(candidate_tables=["assets"]),
        confidence=0.9,
    )


def _context(*, term: dict | None = None) -> dict:
    return {
        "source": "database",
        "metrics": [
            {"metric_code": "customer_count", "metric_name": "客户数量"},
            {"metric_code": "total_asset", "metric_name": "总资产"},
        ],
        "business_terms": [term] if term else [],
        "table_allowlist": ["assets"],
        "join_relationships": [],
    }


def _failures(plan: QueryPlan, question: str, context: dict) -> set[str]:
    return {
        check.error_type
        for check in QueryPlanHardValidator()
        .review(plan, original_question=question, metadata_context=context)
        .hard_checks
        if not check.passed and check.error_type
    }


def test_explicit_threshold_is_grounded_and_ready() -> None:
    question = "找出总资产大于等于100万的客户"
    context = _context()
    plan = ground_query_plan(_plan(), question, context)
    assert plan.plan_status == "ready"
    assert plan.filters[0].provenance[0].source_type == "user_explicit"
    assert _failures(plan, question, context) == set()


def test_hallucinated_threshold_cannot_remain_ready() -> None:
    question = "找出高净值客户"
    context = _context()
    plan = ground_query_plan(_plan(), question, context)
    assert plan.plan_status == "needs_clarification"
    assert not plan.filters
    assert any("高净值" in item.field for item in plan.clarifications)


def test_comparison_operator_must_match_user_wording() -> None:
    question = "找出总资产超过100万的客户"
    plan = _plan()  # >= is not the same as the user's strict >.
    grounded = ground_query_plan(plan, question, _context())
    assert grounded.plan_status == "needs_clarification"
    assert not grounded.filters


def test_same_numeric_value_cannot_borrow_other_filters_operator() -> None:
    question = "交易金额超过50万且总资产至少50万的客户"
    plan = _plan(value=500_000)
    plan.filters[0].operator = ">"
    grounded = ground_query_plan(plan, question, _context())
    assert grounded.plan_status == "needs_clarification"
    assert not grounded.filters


def test_explicit_numeric_range_is_preserved() -> None:
    question = "找出年龄在30到40岁的客户"
    plan = _plan().model_copy(
        update={
            "filters": [
                QueryFilter(
                    term="年龄",
                    operator="between",
                    field_code="age",
                    value=QueryValue(raw="30到40", normalized=[30, 40], value_type="range"),
                    is_resolved=True,
                )
            ],
        }
    )
    grounded = ground_query_plan(plan, question, _context())
    assert grounded.plan_status == "ready"
    assert grounded.filters[0].provenance[0].source_type == "user_explicit"


def test_unrelated_number_in_definition_is_not_threshold_evidence() -> None:
    question = "找出日均资产较高的客户"
    context = _context(
        term={
            "term": "日均资产",
            "definition": "2026年一季度按90天计算日均资产",
            "default_plan_fragment": {},
            "clarification_required": False,
        }
    )
    plan = _plan(value=90, code="total_asset")
    plan.filters[0].term = "日均资产"
    grounded = ground_query_plan(plan, question, context)
    assert grounded.plan_status == "needs_clarification"
    assert not grounded.filters


def test_metadata_threshold_auto_completes_business_term() -> None:
    question = "找出高净值客户"
    context = _context(
        term={
            "term": "高净值",
            "definition": "总资产至少100万",
            "default_plan_fragment": {
                "metric_code": "total_asset",
                "operator": ">=",
                "value": 1_000_000,
            },
            "clarification_required": False,
        }
    )
    plan = _plan().model_copy(update={"filters": []})
    grounded = ground_query_plan(plan, question, context)
    assert grounded.plan_status == "ready"
    assert grounded.filters[0].value.normalized == 1_000_000
    assert grounded.filters[0].provenance[0].source_id == "term:高净值"
    assert _failures(grounded, question, context) == set()


def test_metadata_default_resolves_existing_clarification() -> None:
    question = "找出高净值客户"
    context = _context(
        term={
            "term": "高净值",
            "definition": "总资产至少100万",
            "default_plan_fragment": {
                "metric_code": "total_asset",
                "operator": ">=",
                "value": 1_000_000,
            },
            "clarification_required": False,
        }
    )
    plan = _plan().model_copy(
        update={
            "filters": [],
            "plan_status": "needs_clarification",
            "clarifications": [
                ClarificationQuestion(field="高净值客户", question="门槛是多少？", reason="未定义")
            ],
        }
    )
    grounded = ground_query_plan(plan, question, context)
    assert grounded.plan_status == "ready"
    assert not grounded.clarifications
    assert grounded.filters[0].provenance[0].source_type == "metadata_definition"


def test_new_catalog_term_auto_applies_structured_definition() -> None:
    question = "找出VIP客户"
    context = _context(
        term={
            "term": "VIP客户",
            "definition": "总资产至少200万",
            "default_plan_fragment": {
                "metric_code": "total_asset",
                "operator": ">=",
                "value": 2_000_000,
            },
            "clarification_required": False,
        }
    )
    grounded = ground_query_plan(_plan().model_copy(update={"filters": []}), question, context)
    assert grounded.plan_status == "ready"
    assert grounded.filters[0].term == "VIP客户"
    assert grounded.filters[0].provenance[0].source_id == "term:VIP客户"


def test_forged_provenance_does_not_bypass_hard_review() -> None:
    question = "找出高净值客户"
    fake = _plan()
    fake.filters[0].provenance = [EvidenceRef(source_type="user_explicit", source_text="100万")]
    failures = _failures(fake, question, _context())
    assert "ungrounded_threshold" in failures
    assert "ungrounded_business_definition" in failures


def test_hard_review_requires_metric_provenance_on_ready_plan() -> None:
    question = "找出总资产大于等于100万的客户"
    failures = _failures(_plan(), question, _context())
    assert "ungrounded_metric" in failures
    assert "ungrounded_threshold" in failures


def test_vague_shrinkage_term_needs_definition() -> None:
    question = "找出资产缩水严重的客户"
    plan = _plan().model_copy(update={"filters": []})
    grounded = ground_query_plan(plan, question, _context())
    assert grounded.plan_status == "needs_clarification"
    assert any(item.field == "缩水严重" for item in grounded.clarifications)


def test_ambiguous_metadata_term_requires_clarification() -> None:
    question = "找出高净值客户"
    context = _context(
        term={
            "term": "高净值",
            "definition": "由业务部门确认",
            "default_plan_fragment": {},
            "clarification_required": True,
        }
    )
    plan = ground_query_plan(_plan().model_copy(update={"filters": []}), question, context)
    assert plan.plan_status == "needs_clarification"
    assert any("高净值" in item.field for item in plan.clarifications)


def test_unstated_time_window_requires_clarification() -> None:
    question = "找出最近交易的客户"
    plan = _plan().model_copy(
        update={
            "filters": [],
            "time_range": TimeRange(label="最近30天", relative="last_30_days", is_resolved=False),
        }
    )
    grounded = ground_query_plan(plan, question, _context())
    assert grounded.plan_status == "needs_clarification"
    assert any(item.field == "time_range" for item in grounded.clarifications)


def test_explicit_calendar_quarter_is_grounded_despite_label_variant() -> None:
    question = "统计2026年一季度交易金额"
    plan = _plan().model_copy(
        update={
            "filters": [],
            "time_range": TimeRange(
                label="2026年第一季度",
                start="20260101",
                end="20260331",
                granularity="quarter",
                is_resolved=True,
            ),
        }
    )
    grounded = ground_query_plan(plan, question, _context())
    assert grounded.plan_status == "ready"
    assert grounded.time_range.provenance[0].source_type == "user_explicit"


def test_metric_table_and_join_codes_are_checked_against_metadata() -> None:
    question = "找出总资产大于等于100万的客户"
    context = _context()
    plan = ground_query_plan(_plan(code="invented_metric"), question, context)
    plan = plan.model_copy(
        update={
            "dimensions": [QueryDimension(name="伪字段", dimension_code="fake_column")],
            "data_requirements": DataRequirement(
                candidate_tables=["unknown_table"], required_join_paths=["invented_join"]
            ),
        }
    )
    assert _failures(plan, question, context) == {
        "fabricated_metric",
        "fabricated_field",
        "fabricated_table",
        "fabricated_join",
    }


def test_critic_sees_original_question_separately_from_plan_question() -> None:
    messages = LLMPlanCritic(None)._build_messages(
        _plan(), [], _context(), original_question="实际用户问题"
    )
    assert "原始用户问题（以此为准，不依赖 QueryPlan.question）：" in messages[1].content
    assert "实际用户问题" in messages[1].content
    assert "untrusted plan question" in messages[1].content


def test_actor_and_critic_receive_retrieved_field_and_join_evidence() -> None:
    context = _context()
    context["tables"] = [{"name": "assets", "columns": [{"name": "customer_id"}]}]
    context["join_relationships"] = [
        {
            "id": 7,
            "left_table": "assets",
            "left_column": "customer_id",
            "right_table": "customers",
            "right_column": "id",
        }
    ]
    actor_prompt = (
        LLMQueryPlanActor(None)
        ._build_messages("找出客户", None, None, metadata_context=context)[1]
        .content
    )
    critic_prompt = (
        LLMPlanCritic(None)
        ._build_messages(_plan(), [], context, original_question="找出客户")[1]
        .content
    )
    for prompt in (actor_prompt, critic_prompt):
        assert "customer_id" in prompt
        assert "right_table" in prompt


def test_legacy_structural_validator_signature_still_works() -> None:
    assert QueryPlanHardValidator().review(_plan()).passed


def test_critic_missing_user_condition_is_blocking() -> None:
    decision = ReviewDecision(
        passed=False,
        score=40,
        stage="query_plan_review",
        error_type="missing_user_condition",
        reason="User threshold was omitted.",
        confidence=0.9,
    )
    assert not QueryService._make_plan_critic_decision_advisory(decision).passed
