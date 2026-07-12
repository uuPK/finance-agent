import asyncio
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse

from app.schemas.run import (
    ClarificationSubmission,
    QueryRunCreate,
    QueryRunCreated,
    QueryRunList,
    QueryRunSnapshot,
)
from app.services.query_export_service import QueryExportError, QueryExportService
from app.services.run_service import get_run_manager

router = APIRouter(prefix="/chat/runs", tags=["query-runs"])


@router.post("", response_model=QueryRunCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_run(request: QueryRunCreate) -> QueryRunCreated:
    return await get_run_manager().create_run(request.question, request.user_id)


@router.get("", response_model=QueryRunList)
async def list_runs(
    user_id: str = Query(..., min_length=1, max_length=128),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> QueryRunList:
    manager = get_run_manager()
    items, total = await asyncio.to_thread(manager.repository.list_runs, user_id, limit, offset)
    return QueryRunList(items=items, total=total, limit=limit, offset=offset)


@router.get("/{query_id}", response_model=QueryRunSnapshot)
async def get_run(query_id: UUID) -> QueryRunSnapshot:
    snapshot = await asyncio.to_thread(get_run_manager().repository.get_run, query_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Query run not found.")
    return snapshot


@router.get("/{query_id}/export")
async def export_run(
    query_id: UUID,
    user_id: str = Query(..., min_length=1, max_length=128),
    export_format: str = Query("xlsx", alias="format", pattern="^(xlsx|csv|json)$"),
) -> Response:
    try:
        artifact = await asyncio.to_thread(
            QueryExportService().export,
            query_id,
            user_id,
            export_format,
        )
    except QueryExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return Response(
        content=artifact.content,
        media_type=artifact.media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Export-Row-Count": str(artifact.row_count),
            "X-Export-Truncated": str(artifact.truncated).lower(),
        },
    )


@router.post("/{query_id}/clarifications", response_model=QueryRunSnapshot)
async def submit_clarifications(
    query_id: UUID, submission: ClarificationSubmission
) -> QueryRunSnapshot:
    answers = {answer.field: answer.value for answer in submission.answers}
    if len(answers) != len(submission.answers):
        raise HTTPException(status_code=400, detail="Clarification fields must be unique.")
    try:
        return await get_run_manager().resume_run(query_id, answers)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{query_id}/events")
async def stream_events(
    query_id: UUID,
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
    after: int = Query(0, ge=0),
) -> StreamingResponse:
    manager = get_run_manager()
    snapshot = await asyncio.to_thread(manager.repository.get_run, query_id, False)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Query run not found.")
    cursor = max(after, int(last_event_id or 0))

    async def event_stream():
        nonlocal cursor
        idle_ticks = 0
        while True:
            events = await asyncio.to_thread(manager.repository.list_events, query_id, cursor)
            if events:
                idle_ticks = 0
                for event in events:
                    cursor = event.event_id
                    data = event.model_dump_json()
                    yield f"id: {event.event_id}\nevent: {event.type}\ndata: {data}\n\n"
                    if event.type in {"run.completed", "run.failed", "clarification.required"}:
                        return
            else:
                idle_ticks += 1
                if idle_ticks >= 30:
                    idle_ticks = 0
                    yield ": heartbeat\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
