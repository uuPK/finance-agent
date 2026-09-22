"""Load a seventh held-out 30-case challenge on a disjoint March time window."""
# ruff: noqa: E501

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

from psycopg.types.json import Jsonb

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.session import engine
from db.load_official_challenge_v6_cases import CASES as V6_CASES
from db.load_official_challenge_v6_cases import Case, val

DATASET_VERSION = "official-v1-challenge-v7"
SOURCE_TYPE = "official_challenge_v7"
TAG = "official_challenge_v7"


def _shift_case(case: Case) -> Case:
    """Keep query shapes unseen while changing every evaluation time slice."""
    return replace(
        case,
        code=case.code.replace("V6-", "V7-"),
        question=(
            "独立窗口验证："
            + case.question.replace("2026年3月1日至15日", "2026年3月16日至31日")
            .replace("3月1日至15日", "3月16日至31日")
            .replace("截至2026年3月1日", "截至2026年3月16日")
        ),
        sql=(
            case.sql.replace("'20260301'", "'20260316'")
            .replace("'20260315'", "'20260331'")
        ),
    )


CASES = tuple(_shift_case(case) for case in V6_CASES)


def validate() -> None:
    if len(CASES) != 30 or len({case.code for case in CASES}) != 30:
        raise ValueError("V7 needs 30 unique cases.")
    if len({case.question for case in CASES}) != 30:
        raise ValueError("V7 questions must be unique.")
    if any("mart." not in case.sql.lower() or " limit " not in case.sql.lower() for case in CASES):
        raise ValueError("V7 SQL must be readonly and bounded.")
    if any(".name" in case.sql.lower() for case in CASES):
        raise ValueError("V7 must not read sensitive names.")


def main() -> None:
    validate()
    connection = engine.raw_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "update evaluation.eval_cases set is_active = false where source_type = %s",
                (SOURCE_TYPE,),
            )
            for case in CASES:
                cursor.execute(case.sql)
                columns = [description.name for description in cursor.description]
                rows = [
                    {key: val(value) for key, value in zip(columns, row, strict=True)}
                    for row in cursor.fetchall()
                ]
                expected_result = {
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                    "comparison": "unordered",
                }
                tags = [TAG, "benchmark", case.topic, case.difficulty, case.code.lower()]
                cursor.execute(
                    """
                    insert into evaluation.eval_cases
                        (case_code, question, difficulty, scenario, expected_query_plan, expected_sql,
                         expected_result, scoring_config, dataset_version, source_type, expected_status,
                         tags, is_active)
                    values
                        (%s, %s, %s, 'customer_marketing', %s, %s, %s, %s, %s, %s, 'completed', %s, true)
                    on conflict (case_code) do update set
                        question = excluded.question,
                        difficulty = excluded.difficulty,
                        expected_query_plan = excluded.expected_query_plan,
                        expected_sql = excluded.expected_sql,
                        expected_result = excluded.expected_result,
                        scoring_config = excluded.scoring_config,
                        dataset_version = excluded.dataset_version,
                        source_type = excluded.source_type,
                        tags = excluded.tags,
                        is_active = true,
                        updated_at = now()
                    """,
                    (
                        case.code,
                        case.question,
                        case.difficulty,
                        Jsonb({"intent": "metric_query", "scenario": "customer_marketing"}),
                        case.sql,
                        Jsonb(expected_result),
                        Jsonb({"comparison": "unordered", "require_execution": True}),
                        DATASET_VERSION,
                        SOURCE_TYPE,
                        Jsonb(tags),
                    ),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    print(json.dumps({"loaded_cases": len(CASES), "source_type": SOURCE_TYPE}, ensure_ascii=False))


if __name__ == "__main__":
    main()
