"""Context working-set records and the backwards-compatible prompt projection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ContextItem:
    doc_id: str
    kind: str
    payload: dict[str, Any]
    priority: float
    required: bool = False
    parent_table: str | None = None


@dataclass(slots=True)
class ContextBundle:
    prompt_context: dict[str, Any]
    budget: int
    token_usage: int
    item_ids: list[str] = field(default_factory=list)
    retrieval_trace: list[dict[str, Any]] = field(default_factory=list)
    context_expansion_count: int = 0
    dedup_count: int = 0
    eviction_count: int = 0
    compaction_count: int = 0

    @property
    def tables(self) -> list[dict[str, Any]]:
        return self.prompt_context["tables"]

    @property
    def columns(self) -> list[dict[str, Any]]:
        return [column for table in self.tables for column in table["columns"]]

    @property
    def metrics(self) -> list[dict[str, Any]]:
        return self.prompt_context["metrics"]

    @property
    def business_terms(self) -> list[dict[str, Any]]:
        return self.prompt_context["business_terms"]

    @property
    def join_paths(self) -> list[dict[str, Any]]:
        return self.prompt_context["join_relationships"]

    @property
    def examples(self) -> list[dict[str, Any]]:
        return self.prompt_context["question_examples"]

    @property
    def rules(self) -> list[dict[str, Any]]:
        return self.prompt_context["rule_constraints"]

    def stats(self) -> dict[str, int]:
        return {
            "context_tokens": self.token_usage,
            "context_items": len(self.item_ids),
            "context_expansion_count": self.context_expansion_count,
            "dedup_count": self.dedup_count,
            "eviction_count": self.eviction_count,
            "compaction_count": self.compaction_count,
            "budget": self.budget,
        }


def for_prompt(metadata_context: dict[str, Any]) -> dict[str, Any]:
    """Actors see only the bounded projection; validators keep the full catalog."""
    projected = metadata_context.get("prompt_context")
    return projected if isinstance(projected, dict) else metadata_context
