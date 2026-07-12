from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

from app.schemas.query import QueryRequest
from app.schemas.query_plan import QueryPlan
from app.schemas.run import QueryRunCreated, QueryRunSnapshot
from app.services.query_service import QueryService
from app.services.run_repository import RunRepository


class QueryRunManager:
    def __init__(self, repository: RunRepository | None = None) -> None:
        self.repository = repository or RunRepository()
        self.tasks: set[asyncio.Task[None]] = set()
        self.repository.mark_interrupted()

    async def create_run(self, question: str, user_id: str) -> QueryRunCreated:
        query_id = uuid4()
        await asyncio.to_thread(self.repository.create_run, query_id, question, user_id)
        await self.publish(
            query_id,
            {
                "type": "run.created",
                "stage": "receive_question",
                "status": "running",
                "attempt": 0,
                "summary": "已接收问题，正在启动可信问数流程",
                "output": {"question": question},
            },
        )
        self._start_task(self._execute(query_id, question, user_id, attempt=0))
        return QueryRunCreated(
            query_id=query_id,
            status="running",
            stream_url=f"/api/chat/runs/{query_id}/events",
        )

    async def resume_run(self, query_id: UUID, answers: dict[str, str]) -> QueryRunSnapshot:
        snapshot = await asyncio.to_thread(self.repository.submit_clarifications, query_id, answers)
        if snapshot is None:
            raise LookupError("Query run not found.")
        previous_plan = snapshot.response.query_plan if snapshot.response else None
        rounds = snapshot.clarification_context.get("rounds") or []
        additions = "；".join(f"{field}：{value}" for field, value in answers.items())
        merged_question = f"{snapshot.question}\n用户已明确：{additions}"
        attempt = len(rounds)
        await self.publish(
            query_id,
            {
                "type": "clarification.received",
                "stage": "clarification_received",
                "status": "passed",
                "attempt": attempt,
                "summary": "已合并用户补充信息，继续生成查询计划",
                "output": {"answers": answers},
            },
        )
        self._start_task(
            self._execute(
                query_id,
                merged_question,
                snapshot.user_id or "anonymous",
                attempt=attempt,
                previous_plan=previous_plan,
            )
        )
        return snapshot

    async def publish(self, query_id: UUID, event: dict[str, Any]) -> None:
        await asyncio.to_thread(
            self.repository.append_event,
            query_id,
            event.get("type", "stage.completed"),
            event["stage"],
            event["status"],
            event["summary"],
            event.get("output") or {},
            event.get("attempt", 0),
        )

    async def _execute(
        self,
        query_id: UUID,
        question: str,
        user_id: str,
        attempt: int,
        previous_plan: QueryPlan | None = None,
    ) -> None:
        try:
            service = QueryService(
                event_sink=lambda event: self.publish(query_id, event),
                event_attempt=attempt,
            )
            response = await service.run(
                QueryRequest(question=question, user_id=user_id, include_debug=True),
                query_id=query_id,
                start_audit=False,
                previous_plan=previous_plan,
            )
            await asyncio.to_thread(self.repository.store_response, query_id, response)
            if response.status == "needs_clarification":
                await self.publish(
                    query_id,
                    {
                        "type": "clarification.required",
                        "stage": "clarification",
                        "status": "passed",
                        "attempt": attempt,
                        "summary": "需要补充业务口径后才能继续查询",
                        "output": {
                            "questions": response.query_plan.clarifications
                            if response.query_plan
                            else []
                        },
                    },
                )
                return
            terminal_type = "run.completed" if response.status == "completed" else "run.failed"
            terminal_status = "passed" if response.status == "completed" else "failed"
            await self.publish(
                query_id,
                {
                    "type": terminal_type,
                    "stage": "final_response",
                    "status": terminal_status,
                    "attempt": attempt,
                    "summary": "查询已完成" if response.status == "completed" else "查询未能完成",
                    "output": {"response": response.model_dump(mode="json")},
                },
            )
        except Exception as exc:
            await self.publish(
                query_id,
                {
                    "type": "run.failed",
                    "stage": "runtime",
                    "status": "failed",
                    "attempt": attempt,
                    "summary": "运行过程中发生错误",
                    "output": {"error_type": type(exc).__name__, "error_message": str(exc)},
                },
            )

    def _start_task(self, coroutine: Any) -> None:
        task = asyncio.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


_manager: QueryRunManager | None = None


def get_run_manager() -> QueryRunManager:
    global _manager
    if _manager is None:
        _manager = QueryRunManager()
    return _manager
