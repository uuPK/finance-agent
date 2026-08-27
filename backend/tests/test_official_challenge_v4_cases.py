from db.load_official_challenge_v4_cases import CASES, SOURCE_TYPE, validate


def test_fourth_held_out_challenge_has_thirty_safe_official_cases() -> None:
    validate()

    assert SOURCE_TYPE == "official_challenge_v4"
    assert len(CASES) == 30
    assert len({case.code for case in CASES}) == len(CASES)
    assert len({case.question for case in CASES}) == len(CASES)
    assert all(case.code.startswith("V4-") for case in CASES)
    assert all("mart." in case.sql.lower() for case in CASES)
    assert all(" limit " in case.sql.lower() for case in CASES)
    assert all(".name" not in case.sql.lower() for case in CASES)
