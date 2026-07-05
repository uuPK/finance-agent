from fastapi import APIRouter

from app.core.config import get_settings
from app.schemas.query import QueryRequest, QueryResponse
from app.services.llm_service import LLMService
from app.services.query_service import QueryService

router = APIRouter()


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


@router.post("/evaluation/run")
def run_evaluation() -> dict[str, str]:
    return {"status": "not_implemented"}
