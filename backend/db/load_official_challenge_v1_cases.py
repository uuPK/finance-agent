# ruff: noqa: E501
"""Load the version-1 held-out 30-case challenge set from official tables.

The test definitions are versioned in official_challenge_v1_cases.json. This
loader regenerates expected results from the current official data instead of
storing a database dump or synthetic answers.
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from psycopg.types.json import Jsonb

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import engine

DATASET_VERSION = "official-v1-challenge"
SOURCE_TYPE = "official_challenge"
TAG = "official_challenge"
CASE_FILE = Path(__file__).with_name("official_challenge_v1_cases.json")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _load_definitions() -> list[dict[str, str]]:
    cases = json.loads(CASE_FILE.read_text(encoding="utf-8"))
    if len(cases) != 30:
        raise ValueError("The version-1 held-out challenge set must contain exactly 30 cases.")
    codes = [case["code"] for case in cases]
    questions = [case["question"] for case in cases]
    if len(codes) != len(set(codes)) or len(questions) != len(set(questions)):
        raise ValueError("Challenge case codes and questions must be unique.")
    for case in cases:
        sql = case["sql"].lower()
        if "mart." not in sql or " limit " not in sql or ".name" in sql:
            raise ValueError("{} is not an official, bounded, non-sensitive query.".format(case["code"]))
    return cases


def _result_payload(cursor: Any, sql: str) -> dict[str, Any]:
    cursor.execute(sql)
    columns = [item.name for item in cursor.description]
    rows = [
        {column: _jsonable(value) for column, value in zip(columns, row, strict=True)}
        for row in cursor.fetchall()
    ]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "comparison": "unordered"}


def main() -> None:
    cases = _load_definitions()
    raw_connection = engine.raw_connection()
    try:
        with raw_connection.cursor() as cursor:
            cursor.execute(
                "update evaluation.eval_cases set is_active = false where source_type = %s",
                (SOURCE_TYPE,),
            )
            for case in cases:
                expected_result = _result_payload(cursor, case["sql"])
                tags = [TAG, "benchmark", case["topic"], case["difficulty"], case["code"].lower()]
                expected_plan = {"intent": "metric_query", "scenario": "customer_marketing"}
                cursor.execute(
                    """
                    insert into evaluation.eval_cases
                        (case_code, question, difficulty, scenario, expected_query_plan, expected_sql,
                         expected_result, scoring_config, dataset_version, source_type, expected_status,
                         tags, is_active)
                    values (%s, %s, %s, 'customer_marketing', %s, %s, %s, %s, %s, %s, 'completed', %s, true)
                    on conflict (case_code) do update set
                        question = excluded.question,
                        difficulty = excluded.difficulty,
                        scenario = excluded.scenario,
                        expected_query_plan = excluded.expected_query_plan,
                        expected_sql = excluded.expected_sql,
                        expected_result = excluded.expected_result,
                        scoring_config = excluded.scoring_config,
                        dataset_version = excluded.dataset_version,
                        source_type = excluded.source_type,
                        expected_status = excluded.expected_status,
                        tags = excluded.tags,
                        is_active = true,
                        updated_at = now()
                    """,
                    (
                        case["code"],
                        case["question"],
                        case["difficulty"],
                        Jsonb(expected_plan),
                        case["sql"],
                        Jsonb(expected_result),
                        Jsonb({"comparison": "unordered", "require_execution": True}),
                        DATASET_VERSION,
                        SOURCE_TYPE,
                        Jsonb(tags),
                    ),
                )
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        raw_connection.close()

    difficulty_counts = {
        difficulty: sum(case["difficulty"] == difficulty for case in cases)
        for difficulty in ("simple", "medium", "complex")
    }
    print(
        json.dumps(
            {
                "loaded_cases": len(cases),
                "difficulty_counts": difficulty_counts,
                "source_type": SOURCE_TYPE,
                "is_held_out": True,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
