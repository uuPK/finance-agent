from time import perf_counter

from app.schemas.query import AgentStep, GuardrailCheck, QueryPlan, QueryRequest, QueryResponse


class QueryService:
    async def run(self, request: QueryRequest) -> QueryResponse:
        started_at = perf_counter()

        query_plan = QueryPlan(
            plan_status="draft",
            intent="customer_segmentation",
            question=request.question,
            subject={"name": "客户", "entity_type": "customer"},
            grain={"level": "customer", "keys": ["customer_id"], "description": "客户级"},
            output={"limit": 100},
        )
        sql = "select 1 as placeholder limit 100"
        elapsed_ms = int((perf_counter() - started_at) * 1000)

        return QueryResponse(
            status="planned",
            answer="项目初始化阶段：后端接口已连通，下一阶段将接入真实元数据检索、LLM 和 PostgreSQL 执行。",
            query_plan=query_plan,
            sql=sql,
            result_preview=[{"placeholder": 1}],
            guardrail_checks=[
                GuardrailCheck(
                    name="initialization",
                    passed=True,
                    message="FastAPI skeleton is ready; real Guardrail execution is pending.",
                    severity="info",
                )
            ],
            steps=[
                AgentStep(
                    name="receive_question",
                    status="passed",
                    summary="已接收自然语言问题。",
                    details={"question": request.question},
                ),
                AgentStep(
                    name="build_placeholder_plan",
                    status="passed",
                    summary="已返回初始化阶段 QueryPlan 占位结果。",
                ),
            ],
            elapsed_ms=elapsed_ms,
        )
