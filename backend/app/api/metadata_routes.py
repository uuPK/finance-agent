from fastapi import APIRouter, HTTPException, Query, Response, status

from app.schemas.metadata import (
    MetadataBusinessTerm,
    MetadataBusinessTermInput,
    MetadataJoin,
    MetadataJoinInput,
    MetadataMetric,
    MetadataMetricInput,
    MetadataOverview,
    MetadataQuestionExample,
    MetadataQuestionExampleInput,
    MetadataRuleConstraint,
    MetadataRuleConstraintInput,
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


@router.post("/metrics", response_model=MetadataMetric, status_code=status.HTTP_201_CREATED)
def create_metric(payload: MetadataMetricInput) -> MetadataMetric:
    try:
        return MetadataCatalogService().create_metric(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/metrics/{metric_code}", response_model=MetadataMetric)
def update_metric(metric_code: str, payload: MetadataMetricInput) -> MetadataMetric:
    try:
        return MetadataCatalogService().update_metric(metric_code, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/metrics/{metric_code}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_metric(metric_code: str) -> Response:
    try:
        MetadataCatalogService().deactivate_metric(metric_code)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/terms", response_model=list[MetadataBusinessTerm])
def list_terms(
    search: str | None = Query(None, min_length=1, max_length=128),
) -> list[MetadataBusinessTerm]:
    return MetadataCatalogService().list_terms(search)


@router.post("/terms", response_model=MetadataBusinessTerm, status_code=status.HTTP_201_CREATED)
def create_term(payload: MetadataBusinessTermInput) -> MetadataBusinessTerm:
    try:
        return MetadataCatalogService().create_term(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/terms/{term}", response_model=MetadataBusinessTerm)
def update_term(term: str, payload: MetadataBusinessTermInput) -> MetadataBusinessTerm:
    try:
        return MetadataCatalogService().update_term(term, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/terms/{term}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_term(term: str) -> Response:
    try:
        MetadataCatalogService().deactivate_term(term)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/joins", response_model=list[MetadataJoin])
def list_joins() -> list[MetadataJoin]:
    return MetadataCatalogService().list_joins()


@router.post("/joins", response_model=MetadataJoin, status_code=status.HTTP_201_CREATED)
def create_join(payload: MetadataJoinInput) -> MetadataJoin:
    try:
        return MetadataCatalogService().create_join(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/joins/{join_id}", response_model=MetadataJoin)
def update_join(join_id: int, payload: MetadataJoinInput) -> MetadataJoin:
    try:
        return MetadataCatalogService().update_join(join_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/joins/{join_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_join(join_id: int) -> Response:
    try:
        MetadataCatalogService().deactivate_join(join_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/examples", response_model=list[MetadataQuestionExample])
def list_examples(limit: int = Query(30, ge=1, le=100)) -> list[MetadataQuestionExample]:
    return MetadataCatalogService().list_examples(limit)


@router.post(
    "/examples", response_model=MetadataQuestionExample, status_code=status.HTTP_201_CREATED
)
def create_example(payload: MetadataQuestionExampleInput) -> MetadataQuestionExample:
    return MetadataCatalogService().create_example(payload)


@router.put("/examples/{example_id}", response_model=MetadataQuestionExample)
def update_example(
    example_id: int, payload: MetadataQuestionExampleInput
) -> MetadataQuestionExample:
    try:
        return MetadataCatalogService().update_example(example_id, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/examples/{example_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_example(example_id: int) -> Response:
    try:
        MetadataCatalogService().deactivate_example(example_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/rules", response_model=list[MetadataRuleConstraint])
def list_rules() -> list[MetadataRuleConstraint]:
    return MetadataCatalogService().list_rules()


@router.post("/rules", response_model=MetadataRuleConstraint, status_code=status.HTTP_201_CREATED)
def create_rule(payload: MetadataRuleConstraintInput) -> MetadataRuleConstraint:
    try:
        return MetadataCatalogService().create_rule(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/rules/{rule_code}", response_model=MetadataRuleConstraint)
def update_rule(rule_code: str, payload: MetadataRuleConstraintInput) -> MetadataRuleConstraint:
    try:
        return MetadataCatalogService().update_rule(rule_code, payload)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/rules/{rule_code}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_rule(rule_code: str) -> Response:
    try:
        MetadataCatalogService().deactivate_rule(rule_code)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
