"""Append-only, best-effort telemetry layered over the existing stage event stream."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID, uuid4

from app.llm.protocols import SupportsLLMComplete
from app.llm.schemas import LLMMessage, LLMResponse

EventSink = Callable[[dict[str, Any]], Awaitable[None]]
Clock = Callable[[], float]


@dataclass(slots=True)
class _ActiveSpan:
    span_id: UUID
    parent_span_id: UUID | None
    started_at: float


class TraceRecorder:
    """Adds stage spans and emits bounded trace facts, never workflow decisions."""

    def __init__(
        self, sink: EventSink, clarification_round: int = 0, *, clock: Clock = perf_counter
    ) -> None:
        self.sink = sink
        self.clarification_round = clarification_round
        self.clock = clock
        self._active: dict[tuple[str, int], _ActiveSpan] = {}
        self._order: list[tuple[str, int]] = []
        self.telemetry_write_failures = 0
        self.telemetry_projection_failures = 0

    def _current(self) -> tuple[str, int, _ActiveSpan] | None:
        if not self._order:
            return None
        stage, attempt = self._order[-1]
        return stage, attempt, self._active[(stage, attempt)]

    async def emit_stage(
        self,
        stage: str,
        status: str,
        summary: str,
        output: dict[str, Any] | None = None,
        *,
        stage_attempt: int = 0,
        event_type: str | None = None,
    ) -> None:
        key = (stage, stage_attempt)
        duration_ms: int | None = None
        if status == "running":
            current = self._current()
            span = _ActiveSpan(
                span_id=uuid4(),
                parent_span_id=current[2].span_id if current else None,
                started_at=self.clock(),
            )
            self._active[key] = span
            if key in self._order:
                self._order.remove(key)
            self._order.append(key)
        else:
            span = self._active.pop(key, None)
            if span is None:
                span = _ActiveSpan(uuid4(), None, self.clock())
            else:
                duration_ms = max(0, int((self.clock() - span.started_at) * 1000))
                self._order.remove(key)

        resolved_type = event_type or (
            "stage.started"
            if status == "running"
            else "stage.failed"
            if status == "failed"
            else "stage.completed"
        )
        payload = dict(output or {})
        if self.telemetry_write_failures or self.telemetry_projection_failures:
            payload["trace_warning"] = {
                "telemetry_write_failures": self.telemetry_write_failures,
                "telemetry_projection_failures": self.telemetry_projection_failures,
            }
        await self.sink(
            {
                "type": resolved_type,
                "stage": stage,
                "status": status,
                "attempt": self.clarification_round + stage_attempt,
                "clarification_round": self.clarification_round,
                "stage_attempt": stage_attempt,
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "duration_ms": duration_ms,
                "summary": summary,
                "output": payload,
            }
        )
        self.telemetry_write_failures = 0
        self.telemetry_projection_failures = 0

    async def record(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        status: str = "passed",
        duration_ms: int | None = None,
    ) -> None:
        """A failed telemetry insert is visible on the next stage event, not retried."""
        current = self._current()
        stage, stage_attempt, parent = current if current else (kind, 0, None)
        try:
            await self.sink(
                {
                    "type": f"trace.{kind}",
                    "stage": stage,
                    "status": status,
                    "attempt": self.clarification_round + stage_attempt,
                    "clarification_round": self.clarification_round,
                    "stage_attempt": stage_attempt,
                    "span_id": uuid4(),
                    "parent_span_id": parent.span_id if parent else None,
                    "duration_ms": duration_ms,
                    "summary": kind,
                    "output": payload,
                }
            )
        except Exception:
            self.telemetry_write_failures += 1

    async def close_open_spans(self, error_type: str) -> None:
        """Close interrupted stages without exposing exception messages."""
        while self._order:
            stage, stage_attempt = self._order[-1]
            try:
                await self.emit_stage(
                    stage,
                    "failed",
                    "阶段异常终止",
                    {"error_type": error_type},
                    stage_attempt=stage_attempt,
                )
            except Exception:
                # The original failure still controls the run; do not retry work.
                self.telemetry_write_failures += 1


class TracingLLMService:
    """Observe the final provider response without retrying or retaining messages."""

    def __init__(self, inner: SupportsLLMComplete, recorder: TraceRecorder) -> None:
        self.inner = inner
        self.recorder = recorder

    async def complete(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        started_at = self.recorder.clock()
        try:
            response = await self.inner.complete(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        except Exception as exc:
            await self.recorder.record(
                "llm_call",
                {
                    "error_type": type(exc).__name__,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                },
                status="failed",
                duration_ms=max(0, int((self.recorder.clock() - started_at) * 1000)),
            )
            raise
        usage = response.usage
        await self.recorder.record(
            "llm_call",
            {
                "provider": response.provider,
                "model": response.model,
                "prompt_tokens": usage.prompt_tokens if usage else None,
                "completion_tokens": usage.completion_tokens if usage else None,
                "total_tokens": usage.total_tokens if usage else None,
                "usage_source": "provider_response" if usage else "unavailable",
            },
            duration_ms=max(0, int((self.recorder.clock() - started_at) * 1000)),
        )
        return response
