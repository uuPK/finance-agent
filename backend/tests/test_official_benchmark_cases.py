from db.load_official_benchmark_cases import (
    CASES,
    EXTENSION_CASES,
    EXTENSION_SOURCE_TYPE,
    SOURCE_TYPE,
    _validate_cases,
)


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


def test_held_out_extension_has_thirty_safe_official_cases() -> None:
    _validate_cases()
    assert EXTENSION_SOURCE_TYPE == "official_extension"
    assert len(EXTENSION_CASES) == 30
    assert len({case.code for case in EXTENSION_CASES}) == len(EXTENSION_CASES)
    assert len({case.question for case in EXTENSION_CASES}) == len(EXTENSION_CASES)
    assert all(case.code.startswith("EXT-") for case in EXTENSION_CASES)
    assert all("mart." in case.sql.lower() for case in EXTENSION_CASES)
    assert all(" limit " in case.sql.lower() for case in EXTENSION_CASES)
    assert all(".name" not in case.sql.lower() for case in EXTENSION_CASES)
