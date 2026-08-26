from db.load_official_benchmark_cases import CASES, SOURCE_TYPE, _validate_cases


def test_official_benchmark_has_more_than_fifty_unique_cases() -> None:
    _validate_cases()
    assert len(CASES) == 60
    assert len({case.code for case in CASES}) == len(CASES)
    assert len({case.question for case in CASES}) == len(CASES)


def test_official_benchmark_never_queries_masked_customer_name() -> None:
    assert SOURCE_TYPE == "official_derived"
    assert all("mart." in case.sql.lower() for case in CASES)
    assert all(" limit " in case.sql.lower() for case in CASES)
    assert all(".name" not in case.sql.lower() for case in CASES)
