"""Retrieval-only Recall@K metrics; no SQL/LLM execution or result persistence."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.metadata.retriever import MetadataRetrievalResult


@dataclass(frozen=True, slots=True)
class RetrievalGold:
    tables: frozenset[str] = field(default_factory=frozenset)
    columns: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    metrics: frozenset[str] = field(default_factory=frozenset)
    joins: frozenset[tuple[str, str, str, str]] = field(default_factory=frozenset)


def _recall(expected: set, found: set) -> float | None:
    return len(expected & found) / len(expected) if expected else None


def score_retrieval(
    result: MetadataRetrievalResult, gold: RetrievalGold
) -> dict[str, float | None]:
    """Score retrieved grounded context; None means the gold has no label of that type."""
    found_tables = set(result.table_names)
    found_columns = {
        (str(row["table_name"]), str(row["column_name"]))
        for row in result.matched_columns
    }
    found_metrics = set(result.metric_codes)
    found_joins = {
        (
            str(row["left_table"]),
            str(row["left_column"]),
            str(row["right_table"]),
            str(row["right_column"]),
        )
        for row in result.matched_join_relationships
    }
    return {
        "table_recall": _recall(set(gold.tables), found_tables),
        "column_recall": _recall(set(gold.columns), found_columns),
        "metric_recall": _recall(set(gold.metrics), found_metrics),
        "join_path_recall": _recall(set(gold.joins), found_joins),
    }
