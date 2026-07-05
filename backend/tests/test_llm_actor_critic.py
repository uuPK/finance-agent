import asyncio
import json

from app.agents.llm_plan_critic import LLMPlanCritic
from app.agents.llm_query_plan_actor import LLMQueryPlanActor
from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.llm.schemas import LLMMessage, LLMResponse
from app.schemas.query import QueryRequest
from app.services.query_service import QueryService


class QueueLLMService:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.calls: list[list[LLMMessage]] = []

    async def complete(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        self.calls.append(messages)
        return LLMResponse(
            content=self.contents.pop(0),
            model="fake-model",
            provider="fake-provider",
        )


def test_llm_query_plan_actor_uses_llm_response() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    plan_json = _ready_plan_json(question, confidence=0.91)

    result = asyncio.run(
        LLMQueryPlanActor(QueueLLMService([f"```json\n{plan_json}\n```"])).build(question)
    )

    assert result.source == "llm"
    assert result.plan.confidence == 0.91
    assert result.llm_model == "fake-model"


def test_llm_plan_critic_parses_review_decision() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    plan = RuleBasedQueryPlanActor().build(question)
    critic_json = _passing_critic_json()

    result = asyncio.run(LLMPlanCritic(QueueLLMService([critic_json])).review(plan, []))

    assert result.status == "reviewed"
    assert result.decision is not None
    assert result.decision.passed
    assert result.decision.score == 95


def test_query_service_runs_llm_actor_and_critic_when_service_provided() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    llm_service = QueueLLMService(
        [
            _ready_plan_json(question, confidence=0.93),
            _passing_critic_json(),
        ]
    )

    response = asyncio.run(
        QueryService(llm_service=llm_service).run(QueryRequest(question=question))
    )

    build_step = next(step for step in response.steps if step.name == "build_query_plan")
    critic_step = next(step for step in response.steps if step.name == "query_plan_llm_review")

    assert response.status == "planned"
    assert response.query_plan is not None
    assert response.query_plan.confidence == 0.93
    assert build_step.details["actor_source"] == "llm"
    assert critic_step.status == "passed"
    assert llm_service.contents == []


def test_query_service_repairs_plan_with_critic_feedback() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    llm_service = QueueLLMService(
        [
            _plan_with_limit_exceeding_safety_json(question),
            _ready_plan_json(question, confidence=0.94),
            _passing_critic_json(),
        ]
    )

    response = asyncio.run(
        QueryService(llm_service=llm_service).run(QueryRequest(question=question))
    )

    build_step = next(step for step in response.steps if step.name == "build_query_plan")
    repair_step = next(step for step in response.steps if step.name == "repair_query_plan")

    assert response.status == "planned"
    assert response.retry_count == 1
    assert response.query_plan is not None
    assert response.query_plan.output.limit == 100
    assert build_step.details["attempt_count"] == 2
    assert build_step.details["repair_attempts"] == 1
    assert repair_step.status == "passed"
    assert "limit_exceeds_safety" in llm_service.calls[1][-1].content


def _ready_plan_json(question: str, confidence: float) -> str:
    plan = RuleBasedQueryPlanActor().build(question)
    plan = plan.model_copy(update={"confidence": confidence})
    return json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)


def _plan_with_limit_exceeding_safety_json(question: str) -> str:
    plan = RuleBasedQueryPlanActor().build(question)
    plan = plan.model_copy(update={"output": plan.output.model_copy(update={"limit": 1001})})
    return json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)


def _passing_critic_json() -> str:
    return json.dumps(
        {
            "passed": True,
            "score": 95,
            "stage": "query_plan_review",
            "reason": "QueryPlan aligns with the user request and keeps all key conditions.",
            "evidence": ["semantic_alignment"],
            "repair_hint": None,
            "clarification_questions": [],
            "confidence": 0.9,
        },
        ensure_ascii=False,
    )
