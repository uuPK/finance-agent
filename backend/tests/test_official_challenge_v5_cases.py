from db.load_official_challenge_v5_cases import CASES, SOURCE_TYPE, validate


def test_fifth_held_out_challenge_has_forty_safe_official_cases() -> None:
    validate()

    assert SOURCE_TYPE == "official_challenge_v5"
    assert len(CASES) == 40
    assert len({case.code for case in CASES}) == len(CASES)
    assert len({case.question for case in CASES}) == len(CASES)
    assert all(case.code.startswith("V5-") for case in CASES)
    assert all("mart." in case.sql.lower() for case in CASES)
    assert all(" limit " in case.sql.lower() for case in CASES)
    assert all(".name" not in case.sql.lower() for case in CASES)
