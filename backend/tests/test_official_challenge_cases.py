from db.load_official_challenge_cases import (
    CHALLENGE_CASES,
    CHALLENGE_SOURCE_TYPE,
    _validate_cases,
)


def test_second_held_out_challenge_has_thirty_safe_official_cases() -> None:
    _validate_cases()

    assert CHALLENGE_SOURCE_TYPE == "official_challenge_v2"
    assert len(CHALLENGE_CASES) == 30
    assert len({case.code for case in CHALLENGE_CASES}) == len(CHALLENGE_CASES)
    assert len({case.question for case in CHALLENGE_CASES}) == len(CHALLENGE_CASES)
    assert all(case.code.startswith("NEW-") for case in CHALLENGE_CASES)
    assert all("mart." in case.sql.lower() for case in CHALLENGE_CASES)
    assert all(" limit " in case.sql.lower() for case in CHALLENGE_CASES)
    assert all(".name" not in case.sql.lower() for case in CHALLENGE_CASES)
