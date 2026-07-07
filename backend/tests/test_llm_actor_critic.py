import asyncio
import json

from app.agents.llm_plan_critic import LLMPlanCritic
from app.agents.llm_query_plan_actor import LLMQueryPlanActor
from app.agents.llm_result_critic import LLMResultCritic
from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.llm.schemas import LLMMessage, LLMResponse
from app.schemas.query import QueryRequest
from app.schemas.review import ReviewDecision
from app.schemas.sql import SQLDraft
from app.services.query_service import QueryService
from app.services.sql_executor import SQLExecutionResult


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


class StaticSchemaContextProvider:
    def load(self, query_plan=None) -> dict:
        return {
            "version": "1.0",
            "source": "database",
            "table_count": 4,
            "metric_count": 2,
            "tables": [],
            "metrics": [
                {"metric_code": "current_total_asset"},
                {"metric_code": "trade_count_90d"},
            ],
            "business_terms": [],
            "join_relationships": [],
            "question_examples": [],
            "table_allowlist": [
                "customer_info",
                "customer_current_asset",
                "customer_trade",
                "customer_trade_90d",
            ],
            "sensitive_columns": ["customer_name_masked"],
            "allowed_columns_by_table": {
                "customer_info": ["customer_id", "customer_no", "customer_level"],
                "customer_current_asset": ["customer_id", "total_asset"],
                "customer_trade": ["customer_id", "trade_id", "trade_date"],
                "customer_trade_90d": ["customer_id", "trade_count_90d"],
            },
        }


class StaticSQLExecutor:
    def __init__(self, result: SQLExecutionResult | None = None) -> None:
        self.result = result or SQLExecutionResult(
            status="success",
            sql="",
            columns=["customer_no", "total_asset", "trade_count_3m"],
            rows=[
                {
                    "customer_no": "C000001",
                    "total_asset": 800000.0,
                    "trade_count_3m": 5,
                }
            ],
            row_count=1,
            elapsed_ms=3,
        )
        self.calls: list[str] = []

    def execute(self, sql: str) -> SQLExecutionResult:
        self.calls.append(sql)
        return self.result


class QueueSQLExecutor:
    def __init__(self, results: list[SQLExecutionResult]) -> None:
        self.results = list(results)
        self.calls: list[str] = []

    def execute(self, sql: str) -> SQLExecutionResult:
        self.calls.append(sql)
        result = self.results.pop(0)
        result.sql = sql
        return result


class NoopAuditLogger:
    def start_query_run(self, *args, **kwargs) -> None:
        return None

    def finish_query_run(self, *args, **kwargs) -> None:
        return None

    def log_sql_execution(self, *args, **kwargs) -> str:
        return "00000000-0000-0000-0000-000000000001"

    def log_result_validation(self, *args, **kwargs) -> None:
        return None


def test_llm_query_plan_actor_uses_llm_response() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    plan_json = _ready_plan_json(question, confidence=0.91)

    result = asyncio.run(
        LLMQueryPlanActor(QueueLLMService([f"```json\n{plan_json}\n```"])).build(question)
    )

    assert result.source == "llm"
    assert result.plan.confidence == 0.91
    assert result.llm_model == "fake-model"


def test_llm_query_plan_actor_initial_prompt_has_no_rule_draft() -> None:
    question = "查询近三个月交易次数超过3次的客户列表"
    actor = LLMQueryPlanActor(QueueLLMService([]))

    messages = actor._build_messages(  # noqa: SLF001
        question=question,
        previous_plan=None,
        critic_feedback=None,
    )
    prompt_text = "\n".join(message.content for message in messages)

    assert "规则版 QueryPlan 草稿" not in prompt_text
    assert "JSON 必须能被 QueryPlan schema 校验通过" in prompt_text
    assert "高净值" in prompt_text


def test_llm_query_plan_actor_repair_prompt_includes_critic_feedback() -> None:
    question = "查询近三个月交易次数超过3次的客户列表"
    previous_plan = RuleBasedQueryPlanActor().build(question)
    actor = LLMQueryPlanActor(QueueLLMService([]))

    messages = actor._build_messages(  # noqa: SLF001
        question=question,
        previous_plan=previous_plan,
        critic_feedback=[
            ReviewDecision(
                passed=False,
                score=30,
                stage="query_plan_review",
                error_type="wrong_grain",
                reason="The plan uses the wrong grain.",
                evidence=["grain.level=aggregate"],
                repair_hint="Use customer grain for customer list queries.",
                confidence=0.9,
            )
        ],
    )
    repair_prompt = messages[-1].content

    assert "当前任务模式：根据 critic 反馈修复上一版计划" in repair_prompt
    assert "wrong_grain" in repair_prompt
    assert "上一版 QueryPlan" in repair_prompt


def test_llm_plan_critic_parses_review_decision() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    plan = RuleBasedQueryPlanActor().build(question)
    critic_json = _passing_critic_json()

    result = asyncio.run(LLMPlanCritic(QueueLLMService([critic_json])).review(plan, []))

    assert result.status == "reviewed"
    assert result.decision is not None
    assert result.decision.passed
    assert result.decision.score == 95


def test_llm_plan_critic_prompt_contains_review_rubric() -> None:
    question = "按服务经理统计近30天触达客户数"
    plan = RuleBasedQueryPlanActor().build(question)
    critic = LLMPlanCritic(QueueLLMService([]))

    messages = critic._build_messages(plan, [])  # noqa: SLF001
    prompt_text = "\n".join(message.content for message in messages)

    assert "wrong_grain" in prompt_text
    assert "guessed_business_definition" in prompt_text
    assert "ReviewDecision schema 校验通过" in prompt_text


def test_llm_result_critic_prompt_contains_review_rubric_and_examples() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    plan = RuleBasedQueryPlanActor().build(question)
    sql_draft = SQLDraft.model_validate(json.loads(_sql_draft_json()))
    execution_result = SQLExecutionResult(
        status="success",
        sql=sql_draft.sql,
        columns=["customer_no", "total_asset", "trade_count_90d"],
        rows=[{"customer_no": "C000001", "total_asset": 800000.0, "trade_count_90d": 5}],
        row_count=1,
    )
    critic = LLMResultCritic(QueueLLMService([]))

    messages = critic._build_messages(  # noqa: SLF001
        question=question,
        query_plan=plan,
        sql_draft=sql_draft,
        execution_result=execution_result,
        hard_checks=[],
        metadata_context=StaticSchemaContextProvider().load(plan),
        preview_rows=100,
    )
    prompt_text = "\n".join(message.content for message in messages)

    assert "ResultCritic" in prompt_text
    assert "wrong_result_grain" in prompt_text
    assert "正例" in prompt_text
    assert "反例" in prompt_text
    assert "stage 必须是 result_review" in prompt_text


def test_query_service_runs_llm_actor_and_critic_when_service_provided() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    llm_service = QueueLLMService(
        [
            _ready_plan_json(question, confidence=0.93),
            _passing_critic_json(),
            _sql_draft_json(),
            _passing_sql_critic_json(),
            _passing_result_critic_json(),
        ]
    )

    response = asyncio.run(
        QueryService(
            llm_service=llm_service,
            schema_context_provider=StaticSchemaContextProvider(),
            sql_executor=StaticSQLExecutor(),
            audit_logger=NoopAuditLogger(),
        ).run(QueryRequest(question=question))
    )

    build_step = next(step for step in response.steps if step.name == "build_query_plan")
    critic_step = next(step for step in response.steps if step.name == "query_plan_llm_review")
    sql_step = next(step for step in response.steps if step.name == "generate_sql")
    sql_critic_step = next(step for step in response.steps if step.name == "sql_llm_review")
    result_critic_step = next(
        step for step in response.steps if step.name == "result_llm_review"
    )

    assert response.status == "completed"
    assert response.sql is not None
    assert response.result_preview
    assert response.query_plan is not None
    assert response.query_plan.confidence == 0.93
    assert build_step.details["actor_source"] == "llm"
    assert critic_step.status == "passed"
    assert sql_step.status == "passed"
    assert sql_critic_step.status == "passed"
    assert result_critic_step.status == "passed"
    assert next(step for step in response.steps if step.name == "execute_sql").status == "passed"
    assert next(step for step in response.steps if step.name == "result_hard_review").status == "passed"
    assert "customer_current_asset" in llm_service.calls[2][-1].content
    assert sql_step.details["metadata_context"]["source"] == "database"
    assert llm_service.contents == []


def test_query_service_limits_response_preview_rows() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    llm_service = QueueLLMService(
        [
            _ready_plan_json(question, confidence=0.93),
            _passing_critic_json(),
            _sql_draft_json(),
            _passing_sql_critic_json(),
            _passing_result_critic_json(),
        ]
    )
    sql_result = SQLExecutionResult(
        status="success",
        sql="",
        columns=["customer_no", "total_asset", "trade_count_3m"],
        rows=[
            {"customer_no": "C000001", "total_asset": 800000.0, "trade_count_3m": 5},
            {"customer_no": "C000002", "total_asset": 700000.0, "trade_count_3m": 4},
            {"customer_no": "C000003", "total_asset": 650000.0, "trade_count_3m": 6},
        ],
        row_count=3,
        elapsed_ms=3,
    )

    response = asyncio.run(
        QueryService(
            llm_service=llm_service,
            schema_context_provider=StaticSchemaContextProvider(),
            sql_executor=StaticSQLExecutor(sql_result),
            audit_logger=NoopAuditLogger(),
            result_preview_rows=2,
        ).run(QueryRequest(question=question))
    )

    execution_step = next(step for step in response.steps if step.name == "execute_sql")

    assert response.status == "completed"
    assert len(response.result_preview) == 2
    assert execution_step.details["row_count"] == 3
    assert execution_step.details["response_preview_rows"] == 2


def test_query_service_repairs_plan_with_critic_feedback() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    llm_service = QueueLLMService(
        [
            _plan_with_limit_exceeding_safety_json(question),
            _ready_plan_json(question, confidence=0.94),
            _passing_critic_json(),
            _sql_draft_json(),
            _passing_sql_critic_json(),
            _passing_result_critic_json(),
        ]
    )

    response = asyncio.run(
        QueryService(
            llm_service=llm_service,
            schema_context_provider=StaticSchemaContextProvider(),
            sql_executor=StaticSQLExecutor(),
            audit_logger=NoopAuditLogger(),
        ).run(QueryRequest(question=question))
    )

    build_step = next(step for step in response.steps if step.name == "build_query_plan")
    repair_step = next(step for step in response.steps if step.name == "repair_query_plan")

    assert response.status == "completed"
    assert response.sql is not None
    assert response.retry_count == 1
    assert response.query_plan is not None
    assert response.query_plan.output.limit == 100
    assert build_step.details["attempt_count"] == 2
    assert build_step.details["repair_attempts"] == 1
    assert repair_step.status == "passed"
    assert "limit_exceeds_safety" in llm_service.calls[1][-1].content


def test_query_service_repairs_sql_with_guardrail_feedback() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    llm_service = QueueLLMService(
        [
            _ready_plan_json(question, confidence=0.93),
            _passing_critic_json(),
            _sql_draft_json(include_limit=False),
            _sql_draft_json(include_limit=True),
            _passing_sql_critic_json(),
            _passing_result_critic_json(),
        ]
    )

    response = asyncio.run(
        QueryService(
            llm_service=llm_service,
            schema_context_provider=StaticSchemaContextProvider(),
            sql_executor=StaticSQLExecutor(),
            audit_logger=NoopAuditLogger(),
        ).run(QueryRequest(question=question))
    )

    repair_sql_step = next(step for step in response.steps if step.name == "repair_sql")
    sql_hard_step = next(step for step in response.steps if step.name == "sql_hard_review")

    assert response.status == "completed"
    assert response.sql is not None
    assert response.retry_count == 1
    assert repair_sql_step.status == "passed"
    assert sql_hard_step.status == "passed"
    assert "limit_required" in llm_service.calls[3][-1].content


def test_query_service_repairs_sql_with_execution_feedback() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    llm_service = QueueLLMService(
        [
            _ready_plan_json(question, confidence=0.93),
            _passing_critic_json(),
            _sql_draft_json(),
            _passing_sql_critic_json(),
            _sql_draft_json(),
            _passing_sql_critic_json(),
            _passing_result_critic_json(),
        ]
    )
    sql_executor = QueueSQLExecutor(
        [
            SQLExecutionResult(
                status="failed",
                sql="",
                error_type="column_not_found",
                error_message="column c.missing_column does not exist",
            ),
            SQLExecutionResult(
                status="success",
                sql="",
                columns=["customer_no", "total_asset", "trade_count_3m"],
                rows=[
                    {
                        "customer_no": "C000001",
                        "total_asset": 800000.0,
                        "trade_count_3m": 5,
                    }
                ],
                row_count=1,
                elapsed_ms=4,
            ),
        ]
    )

    response = asyncio.run(
        QueryService(
            llm_service=llm_service,
            schema_context_provider=StaticSchemaContextProvider(),
            sql_executor=sql_executor,
            audit_logger=NoopAuditLogger(),
        ).run(QueryRequest(question=question))
    )

    repair_sql_step = next(step for step in response.steps if step.name == "repair_sql")
    execution_step = next(step for step in response.steps if step.name == "execute_sql")

    assert response.status == "completed"
    assert response.retry_count == 1
    assert len(sql_executor.calls) == 2
    assert repair_sql_step.status == "passed"
    assert execution_step.status == "passed"
    assert "column_not_found" in llm_service.calls[4][-1].content


def test_query_service_repairs_sql_with_result_critic_feedback() -> None:
    question = "查询近三个月交易次数超过3次且当前资产大于50万的客户列表"
    llm_service = QueueLLMService(
        [
            _ready_plan_json(question, confidence=0.93),
            _passing_critic_json(),
            _sql_draft_json(),
            _passing_sql_critic_json(),
            _failing_result_critic_json(),
            _sql_draft_json(),
            _passing_sql_critic_json(),
            _passing_result_critic_json(),
        ]
    )
    sql_executor = QueueSQLExecutor(
        [
            SQLExecutionResult(
                status="success",
                sql="",
                columns=["customer_no", "total_asset", "trade_count_3m"],
                rows=[
                    {
                        "customer_no": "C000001",
                        "total_asset": 800000.0,
                        "trade_count_3m": 5,
                    }
                ],
                row_count=1,
                elapsed_ms=4,
            ),
            SQLExecutionResult(
                status="success",
                sql="",
                columns=["customer_no", "total_asset", "trade_count_3m"],
                rows=[
                    {
                        "customer_no": "C000001",
                        "total_asset": 800000.0,
                        "trade_count_3m": 5,
                    }
                ],
                row_count=1,
                elapsed_ms=4,
            ),
        ]
    )

    response = asyncio.run(
        QueryService(
            llm_service=llm_service,
            schema_context_provider=StaticSchemaContextProvider(),
            sql_executor=sql_executor,
            audit_logger=NoopAuditLogger(),
        ).run(QueryRequest(question=question))
    )

    repair_sql_step = next(step for step in response.steps if step.name == "repair_sql")
    result_critic_step = next(
        step for step in response.steps if step.name == "result_llm_review"
    )

    assert response.status == "completed"
    assert response.retry_count == 1
    assert len(sql_executor.calls) == 2
    assert repair_sql_step.status == "passed"
    assert result_critic_step.status == "passed"
    assert "wrong_result_grain" in llm_service.calls[5][-1].content


def test_query_service_returns_failed_for_invalid_plan_without_repair() -> None:
    question = "把筛选出的客户手机号导出来"
    llm_service = QueueLLMService([_invalid_sensitive_plan_json(question)])

    response = asyncio.run(
        QueryService(llm_service=llm_service).run(QueryRequest(question=question))
    )

    repair_step = next(step for step in response.steps if step.name == "repair_query_plan")
    critic_step = next(step for step in response.steps if step.name == "query_plan_llm_review")

    assert response.status == "failed"
    assert response.retry_count == 0
    assert response.query_plan is not None
    assert response.query_plan.plan_status == "invalid"
    assert repair_step.status == "skipped"
    assert critic_step.status == "skipped"
    assert len(llm_service.calls) == 1


def _ready_plan_json(question: str, confidence: float) -> str:
    plan = RuleBasedQueryPlanActor().build(question)
    plan = plan.model_copy(update={"confidence": confidence})
    return json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)


def _plan_with_limit_exceeding_safety_json(question: str) -> str:
    plan = RuleBasedQueryPlanActor().build(question)
    plan = plan.model_copy(
        update={"output": plan.output.model_copy(update={"limit": 1001})}
    )
    return json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)


def _invalid_sensitive_plan_json(question: str) -> str:
    plan = RuleBasedQueryPlanActor().build(question)
    plan = plan.model_copy(
        update={
            "plan_status": "invalid",
            "question": question,
            "confidence": 0.2,
            "output": plan.output.model_copy(update={"columns": ["客户", "手机号"]}),
        }
    )
    return json.dumps(plan.model_dump(mode="json"), ensure_ascii=False)


def _sql_draft_json(include_limit: bool = True) -> str:
    limit_clause = " LIMIT 100" if include_limit else ""
    sql = (
        "SELECT c.customer_no, a.total_asset, "
        "COUNT(t.trade_id) AS trade_count_3m "
        "FROM mart.customer_info c "
        "JOIN mart.customer_current_asset a ON a.customer_id = c.customer_id "
        "JOIN mart.customer_trade t ON t.customer_id = c.customer_id "
        "WHERE a.total_asset > 500000 "
        "AND t.trade_date >= CURRENT_DATE - INTERVAL '3 months' "
        "GROUP BY c.customer_no, a.total_asset "
        "HAVING COUNT(t.trade_id) > 3"
        f"{limit_clause}"
    )
    return json.dumps(
        {
            "sql": sql,
            "dialect": "postgres",
            "tables": ["customer_info", "customer_current_asset", "customer_trade"],
            "columns": [
                "customer_no",
                "total_asset",
                "trade_id",
                "trade_date",
            ],
            "assumptions": [],
            "confidence": 0.82,
        },
        ensure_ascii=False,
    )


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


def _passing_sql_critic_json() -> str:
    return json.dumps(
        {
            "passed": True,
            "score": 94,
            "stage": "sql_review",
            "reason": "SQL implements the QueryPlan filters, time window, and grain.",
            "evidence": ["filters_covered", "time_window_covered", "grain_covered"],
            "repair_hint": None,
            "clarification_questions": [],
            "confidence": 0.91,
        },
        ensure_ascii=False,
    )


def _passing_result_critic_json() -> str:
    return json.dumps(
        {
            "passed": True,
            "score": 94,
            "stage": "result_review",
            "reason": "Result columns and grain support the user question.",
            "evidence": ["columns_covered", "grain_covered", "row_count_valid"],
            "repair_hint": None,
            "clarification_questions": [],
            "confidence": 0.91,
        },
        ensure_ascii=False,
    )


def _failing_result_critic_json() -> str:
    return json.dumps(
        {
            "passed": False,
            "score": 45,
            "stage": "result_review",
            "error_type": "wrong_result_grain",
            "reason": "The result does not provide the customer-level detail required.",
            "evidence": ["QueryPlan grain=customer", "Result grain is ambiguous"],
            "repair_hint": "Regenerate SQL to return customer-level rows with identifiers.",
            "clarification_questions": [],
            "confidence": 0.9,
        },
        ensure_ascii=False,
    )
