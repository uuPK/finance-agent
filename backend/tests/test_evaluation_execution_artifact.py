from app.schemas.query import EvaluationExecutionArtifact, QueryResponse
from app.services.evaluation_service import EvaluationManager


def _case(expected_rows: list[dict[str, object]]) -> dict[str, object]:
    return {
        "expected_status": "completed",
        "expected_query_plan": {},
        "expected_result": {"rows": expected_rows},
        "difficulty": "simple",
    }


def _response(rows: list[dict[str, object]], *, truncated: bool = False) -> QueryResponse:
    response = QueryResponse(
        status="completed",
        answer="done",
        sql="select customer_count from result",
        result_preview=rows[:1],
    )
    response._evaluation_execution_artifact = EvaluationExecutionArtifact(
        status="success",
        columns=["customer_count"],
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
    )
    return response


def test_evaluation_scores_complete_rows_instead_of_preview() -> None:
    expected = [{"customer_count": 2}, {"customer_count": 1}]
    response = _response(expected)

    score = EvaluationManager()._score(_case(expected), response, None, 10)

    assert response.result_preview == expected[:1]
    assert score["result_correct"] is True
    assert score["passed"] is True


def test_evaluation_does_not_pass_truncated_execution_artifact() -> None:
    expected = [{"customer_count": 2}]
    response = _response(expected, truncated=True)

    score = EvaluationManager()._score(_case(expected), response, None, 10)

    assert score["executable"] is True
    assert score["result_correct"] is False
    assert score["passed"] is False


def test_evaluation_does_not_fall_back_to_preview_without_artifact() -> None:
    expected = [{"customer_count": 2}]
    response = QueryResponse(
        status="completed",
        answer="done",
        sql="select customer_count from result",
        result_preview=expected,
    )

    score = EvaluationManager()._score(_case(expected), response, None, 10)

    assert score["result_correct"] is False
    assert score["passed"] is False


def test_evaluation_artifact_is_not_part_of_public_response_payload() -> None:
    response = _response([{"customer_count": 2}])

    payload = response.model_dump(mode="json")

    assert "_evaluation_execution_artifact" not in payload
    assert "evaluation_execution_artifact" not in payload
    assert "evaluation_execution_artifact" not in QueryResponse.model_json_schema()
