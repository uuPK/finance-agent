from fastapi import APIRouter, HTTPException, Query

from app.schemas.metadata import (
    MetadataBusinessTerm,
    MetadataJoin,
    MetadataMetric,
    MetadataOverview,
    MetadataQuestionExample,
    MetadataTable,
    MetadataTableDetail,
)
from app.services.metadata_catalog_service import MetadataCatalogService

router = APIRouter(prefix="/metadata", tags=["metadata"])


@router.get("/overview", response_model=MetadataOverview)
def metadata_overview() -> MetadataOverview:
    return MetadataCatalogService().overview()


@router.get("/tables", response_model=list[MetadataTable])
def list_tables(
    search: str | None = Query(None, min_length=1, max_length=128),
) -> list[MetadataTable]:
    return MetadataCatalogService().list_tables(search)


@router.get("/tables/{table_name}", response_model=MetadataTableDetail)
def get_table(table_name: str) -> MetadataTableDetail:
    table = MetadataCatalogService().get_table(table_name)
    if table is None:
        raise HTTPException(status_code=404, detail="Metadata table not found.")
    return table


@router.get("/metrics", response_model=list[MetadataMetric])
def list_metrics(
    search: str | None = Query(None, min_length=1, max_length=128),
) -> list[MetadataMetric]:
    return MetadataCatalogService().list_metrics(search)


@router.get("/terms", response_model=list[MetadataBusinessTerm])
def list_terms(
    search: str | None = Query(None, min_length=1, max_length=128),
) -> list[MetadataBusinessTerm]:
    return MetadataCatalogService().list_terms(search)


@router.get("/joins", response_model=list[MetadataJoin])
def list_joins() -> list[MetadataJoin]:
    return MetadataCatalogService().list_joins()


@router.get("/examples", response_model=list[MetadataQuestionExample])
def list_examples(limit: int = Query(30, ge=1, le=100)) -> list[MetadataQuestionExample]:
    return MetadataCatalogService().list_examples(limit)
