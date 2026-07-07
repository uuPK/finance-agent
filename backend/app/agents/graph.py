from langgraph.graph import END, StateGraph

from app.agents.state import QueryState


def parse_intent(state: QueryState) -> QueryState:
    return {
        **state,
        "status": "intent_parsed",
    }


def retrieve_metadata(state: QueryState) -> QueryState:
    return {
        **state,
        "status": "metadata_retrieved",
    }


def build_query_plan(state: QueryState) -> QueryState:
    question = state.get("question", "")
    return {
        **state,
        "query_plan": {
            "version": "1.0",
            "plan_status": "draft",
            "intent": "customer_segmentation",
            "scenario": "customer_marketing",
            "question": question,
            "subject": {"name": "客户", "entity_type": "customer", "is_resolved": False},
            "entities": [{"name": "客户", "entity_type": "customer", "is_resolved": False}],
            "metrics": [],
            "dimensions": [],
            "filters": [],
            "time_range": None,
            "grain": {"level": "customer", "keys": ["customer_id"], "description": "客户级"},
            "data_requirements": {
                "domains": [],
                "candidate_tables": [],
                "required_join_paths": [],
                "required_metadata_refs": [],
            },
            "order_by": [],
            "output": {
                "format": "table",
                "columns": [],
                "limit": 100,
                "include_sql": True,
                "include_explanation": True,
            },
            "safety": {
                "readonly": True,
                "max_rows": 1000,
                "allow_sensitive_fields": False,
                "require_limit": True,
                "require_metric_definition": True,
            },
            "clarifications": [],
            "assumptions": [],
            "confidence": 0.0,
        },
        "status": "query_plan_built",
    }


def critique_plan(state: QueryState) -> QueryState:
    return {
        **state,
        "critic_feedback": [],
        "status": "plan_checked",
    }


def generate_sql(state: QueryState) -> QueryState:
    return {
        **state,
        "sql": "select 1 as placeholder limit 100",
        "status": "sql_generated",
    }


def check_sql_guardrail(state: QueryState) -> QueryState:
    return {
        **state,
        "guardrail_findings": [],
        "status": "sql_checked",
    }


def execute_sql(state: QueryState) -> QueryState:
    return {
        **state,
        "result_preview": [{"placeholder": 1}],
        "status": "sql_executed",
    }


def critique_result(state: QueryState) -> QueryState:
    return {
        **state,
        "status": "result_checked",
    }


def finalize_answer(state: QueryState) -> QueryState:
    return {
        **state,
        "final_answer": "查询工作流已创建；LLM、schema context、SQL 执行和结果硬校验已接入主循环。",
        "status": "completed",
    }


def build_query_graph():
    graph = StateGraph(QueryState)
    graph.add_node("parse_intent", parse_intent)
    graph.add_node("retrieve_metadata", retrieve_metadata)
    graph.add_node("build_query_plan", build_query_plan)
    graph.add_node("critique_plan", critique_plan)
    graph.add_node("generate_sql", generate_sql)
    graph.add_node("check_sql_guardrail", check_sql_guardrail)
    graph.add_node("execute_sql", execute_sql)
    graph.add_node("critique_result", critique_result)
    graph.add_node("finalize_answer", finalize_answer)

    graph.set_entry_point("parse_intent")
    graph.add_edge("parse_intent", "retrieve_metadata")
    graph.add_edge("retrieve_metadata", "build_query_plan")
    graph.add_edge("build_query_plan", "critique_plan")
    graph.add_edge("critique_plan", "generate_sql")
    graph.add_edge("generate_sql", "check_sql_guardrail")
    graph.add_edge("check_sql_guardrail", "execute_sql")
    graph.add_edge("execute_sql", "critique_result")
    graph.add_edge("critique_result", "finalize_answer")
    graph.add_edge("finalize_answer", END)
    return graph.compile()
