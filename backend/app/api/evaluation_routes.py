# ruff: noqa: E501
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import Response

from app.schemas.evaluation import (
    EvaluationDashboard,
    EvaluationRunCreate,
    EvaluationRunCreated,
    EvaluationRunDetail,
    EvaluationRunSummary,
    ReviewBatchCreate,
    ReviewBatchSummary,
    ReviewImportRequest,
    ReviewImportResult,
    ReviewItemDetail,
)
from app.services.evaluation_service import get_evaluation_manager

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/dashboard", response_model=EvaluationDashboard)
async def get_dashboard() -> EvaluationDashboard:
    return await asyncio.to_thread(get_evaluation_manager().repository.dashboard)


@router.post("/runs", response_model=EvaluationRunCreated, status_code=status.HTTP_202_ACCEPTED)
async def create_evaluation_run(payload: EvaluationRunCreate) -> EvaluationRunCreated:
    eval_run_id = await get_evaluation_manager().start_run(
        payload.run_name, payload.difficulty, payload.limit, payload.evaluation_mode
    )
    return EvaluationRunCreated(eval_run_id=eval_run_id, status="running")


@router.get("/runs", response_model=list[EvaluationRunSummary])
async def list_evaluation_runs(limit: int = Query(20, ge=1, le=100)) -> list[EvaluationRunSummary]:
    return await asyncio.to_thread(get_evaluation_manager().repository.list_runs, limit)


@router.get("/runs/{eval_run_id}", response_model=EvaluationRunDetail)
async def get_evaluation_run(eval_run_id: UUID) -> EvaluationRunDetail:
    run = await asyncio.to_thread(get_evaluation_manager().repository.get_run, eval_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found.")
    return run


@router.post("/review-batches", response_model=ReviewBatchSummary, status_code=status.HTTP_201_CREATED)
async def create_review_batch(payload: ReviewBatchCreate) -> ReviewBatchSummary:
    try:
        return await asyncio.to_thread(
            get_evaluation_manager().repository.create_review_batch,
            payload.eval_run_id,
            payload.batch_name,
            payload.max_items,
            payload.created_by,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/review-batches", response_model=list[ReviewBatchSummary])
async def list_review_batches(limit: int = Query(30, ge=1, le=100)) -> list[ReviewBatchSummary]:
    return await asyncio.to_thread(get_evaluation_manager().repository.list_review_batches, limit)


@router.get("/review-items", response_model=list[ReviewItemDetail])
async def list_review_items(
    batch_id: UUID | None = None,
    review_status: str = Query("pending", alias="status"),
) -> list[ReviewItemDetail]:
    return await asyncio.to_thread(
        get_evaluation_manager().repository.list_review_items, batch_id, review_status
    )


@router.get("/review-batches/{batch_id}/export")
async def export_review_batch(
    batch_id: UUID,
    export_format: str = Query("csv", alias="format", pattern="^(csv|jsonl)$"),
) -> Response:
    content_type, payload = await asyncio.to_thread(
        get_evaluation_manager().repository.export_review_batch, batch_id, export_format
    )
    return Response(
        content=payload,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="review-{batch_id}.{export_format}"'},
    )


@router.post("/review-imports", response_model=ReviewImportResult)
async def import_review_decisions(payload: ReviewImportRequest) -> ReviewImportResult:
    return await asyncio.to_thread(get_evaluation_manager().repository.import_decisions, payload.decisions)
