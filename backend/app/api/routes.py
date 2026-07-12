from fastapi import APIRouter

from app.api.evaluation_routes import router as evaluation_router
from app.api.run_routes import router as run_router
from app.core.config import get_settings
from app.schemas.query import QueryRequest, QueryResponse
from app.services.llm_service import LLMService
from app.services.query_service import QueryService

router = APIRouter()
router.include_router(run_router)
router.include_router(evaluation_router)


@router.get("/health")
def health() -> dict[str, str]:
    settings = get_settings()
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


@router.get("/llm/status")
def llm_status() -> dict[str, str | bool | int]:
    return LLMService().status()


@router.post("/chat/query", response_model=QueryResponse)
async def query(request: QueryRequest) -> QueryResponse:
    service = QueryService()
    return await service.run(request)


@router.get("/metadata/tables")
def list_tables() -> dict[str, list[dict[str, str]]]:
    return {"items": []}


@router.get("/metadata/metrics")
def list_metrics() -> dict[str, list[dict[str, str]]]:
    return {"items": []}
