from typing import Any, TypedDict


class QueryState(TypedDict, total=False):
    question: str
    query_plan: dict[str, Any]
    sql: str
    result_preview: list[dict[str, Any]]
    guardrail_findings: list[dict[str, Any]]
    critic_feedback: list[dict[str, Any]]
    retry_count: int
    max_retry: int
    final_answer: str
    status: str
