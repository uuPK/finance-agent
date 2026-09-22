from db.load_official_challenge_v7_cases import CASES, SOURCE_TYPE, validate


def test_seventh_held_out_challenge_has_thirty_safe_official_cases() -> None:
    validate()

    assert SOURCE_TYPE == "official_challenge_v7"
    assert len(CASES) == 30
    assert len({case.code for case in CASES}) == 30
    assert len({case.question for case in CASES}) == 30
    assert all(case.code.startswith("V7-") for case in CASES)
    assert all("mart." in case.sql.lower() for case in CASES)
    assert all(" limit " in case.sql.lower() for case in CASES)
    assert all(".name" not in case.sql.lower() for case in CASES)
