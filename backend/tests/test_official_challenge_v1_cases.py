from db.load_official_challenge_v1_cases import SOURCE_TYPE, _load_definitions


def test_first_held_out_challenge_has_thirty_safe_official_cases() -> None:
    cases = _load_definitions()

    assert SOURCE_TYPE == "official_challenge"
    assert len(cases) == 30
    assert len({case["code"] for case in cases}) == len(cases)
    assert len({case["question"] for case in cases}) == len(cases)
    assert all(case["code"].startswith("CHL-") for case in cases)
    assert all("mart." in case["sql"].lower() for case in cases)
    assert all(" limit " in case["sql"].lower() for case in cases)
    assert all(".name" not in case["sql"].lower() for case in cases)
