import pytest
from pydantic import ValidationError

from app.schemas.evaluation import EvaluationRunCreate


def test_evaluation_run_can_select_the_held_out_extension() -> None:
    payload = EvaluationRunCreate(case_source="official_extension", limit=30)

    assert payload.case_source == "official_extension"
    assert payload.limit == 30


def test_evaluation_run_can_select_the_second_held_out_challenge() -> None:
    payload = EvaluationRunCreate(case_source="official_challenge_v2", limit=30)

    assert payload.case_source == "official_challenge_v2"
    assert payload.limit == 30


def test_evaluation_run_rejects_unknown_case_sources() -> None:
    with pytest.raises(ValidationError):
        EvaluationRunCreate(case_source="untrusted_source")
