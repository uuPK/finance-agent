"""Run-scoped stage ledger and repair budgets; never stores raw prompts or rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

RepairDomain = Literal["plan", "sql"]


@dataclass(slots=True)
class StageState:
    name: str
    clarification_round: int
    stage_attempt: int
    span_id: UUID | None = None
    parent_span_id: UUID | None = None
    status: str = "pending"
    duration_ms: int | None = None
    input_refs: set[str] = field(default_factory=set)
    output_refs: set[str] = field(default_factory=set)


@dataclass(slots=True)
class HarnessState:
    query_id: UUID
    clarification_round: int
    max_plan_repairs: int
    max_sql_repairs: int
    max_context_refreshes: int = 2
    plan_repairs_used: int = 0
    sql_repairs_used: int = 0
    context_refreshes_used: int = 0
    current_stage: str | None = None
    stages: dict[tuple[str, int], StageState] = field(default_factory=dict)
    llm_calls: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    context_tokens_estimated: int | None = None
    retrieval_calls: int = 0
    route_count: int = 0

    def __post_init__(self) -> None:
        if (
            self.clarification_round < 0
            or self.max_plan_repairs < 0
            or self.max_sql_repairs < 0
            or self.max_context_refreshes < 0
        ):
            raise ValueError("Harness coordinates and repair limits must be non-negative")

    def repair_used(self, domain: RepairDomain) -> int:
        return self.plan_repairs_used if domain == "plan" else self.sql_repairs_used

    def repair_limit(self, domain: RepairDomain) -> int:
        return self.max_plan_repairs if domain == "plan" else self.max_sql_repairs

    def can_repair(self, domain: RepairDomain) -> bool:
        return self.repair_used(domain) < self.repair_limit(domain)

    def reserve_repair(self, domain: RepairDomain) -> int:
        """Reserve before re-running a stage; never permit an over-budget attempt."""
        if not self.can_repair(domain):
            raise RuntimeError(f"{domain} repair budget exhausted")
        if domain == "plan":
            self.plan_repairs_used += 1
            return self.plan_repairs_used
        self.sql_repairs_used += 1
        return self.sql_repairs_used

    def next_route_attempt(self) -> int:
        self.route_count += 1
        return self.route_count

    def can_refresh_context(self) -> bool:
        return self.context_refreshes_used < self.max_context_refreshes

    def reserve_context_refresh(self) -> int:
        if not self.can_refresh_context():
            raise RuntimeError("context refresh budget exhausted")
        self.context_refreshes_used += 1
        return self.context_refreshes_used

    @property
    def total_retries(self) -> int:
        return self.plan_repairs_used + self.sql_repairs_used

    def budget_facts(self, domain: RepairDomain) -> dict[str, int | str | bool]:
        return {
            "domain": domain,
            "used": self.repair_used(domain),
            "limit": self.repair_limit(domain),
            "exhausted": not self.can_repair(domain),
        }

    def observe_stage(self, event: dict[str, Any]) -> None:
        """Index a persisted stage event using the exact Trace coordinates/span."""
        if event.get("type", "").startswith("trace."):
            return
        round_number = event.get("clarification_round")
        if round_number != self.clarification_round:
            raise ValueError("Stage event belongs to another clarification round")
        stage = event["stage"]
        attempt = event["stage_attempt"]
        key = (stage, attempt)
        record = self.stages.get(key)
        if record is None:
            record = StageState(stage, self.clarification_round, attempt)
            self.stages[key] = record
        record.span_id = event.get("span_id")
        record.parent_span_id = event.get("parent_span_id")
        record.status = event["status"]
        record.duration_ms = event.get("duration_ms")
        self.current_stage = stage

    def observe_telemetry(self, event: dict[str, Any]) -> None:
        """Keep only IDs and numeric usage; payload remains in append-only Trace."""
        kind = event.get("type")
        stage = event.get("stage")
        attempt = event.get("stage_attempt")
        record = self.stages.get((stage, attempt))
        payload = event.get("output") or {}
        if not isinstance(payload, dict):
            return
        if kind == "trace.context_selection":
            refs = self._ids(payload.get("selected_item_ids"))
            if record is not None:
                target = record.output_refs if stage == "retrieve_metadata" else record.input_refs
                target.update(refs)
            tokens = payload.get("context_tokens_estimated")
            if isinstance(tokens, int) and tokens >= 0:
                self.context_tokens_estimated = tokens
            calls = payload.get("retrieval_calls")
            if isinstance(calls, int) and calls >= 0:
                self.retrieval_calls = max(self.retrieval_calls, calls)
        elif kind == "trace.plan_evidence" and record is not None:
            for item in payload.get("evidence_items") or []:
                if not isinstance(item, dict):
                    continue
                reference = item.get("metadata_ref_id")
                if isinstance(reference, str):
                    record.output_refs.add(reference)
                for source in item.get("evidence") or []:
                    if isinstance(source, dict) and isinstance(source.get("source_id"), str):
                        record.output_refs.add(source["source_id"])
        elif kind == "trace.sql_execution" and record is not None:
            execution_id = payload.get("execution_id")
            if isinstance(execution_id, str):
                record.output_refs.add(execution_id)
        elif kind == "trace.llm_call":
            self.llm_calls += 1
            self.prompt_tokens = self._add_usage(self.prompt_tokens, payload.get("prompt_tokens"))
            self.completion_tokens = self._add_usage(
                self.completion_tokens, payload.get("completion_tokens")
            )

    @staticmethod
    def _ids(value: Any) -> set[str]:
        if not isinstance(value, list):
            return set()
        return {item for item in value if isinstance(item, str)}

    @staticmethod
    def _add_usage(current: int | None, added: Any) -> int | None:
        return (current or 0) + added if isinstance(added, int) and added >= 0 else current
