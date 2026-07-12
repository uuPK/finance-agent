from fastapi.testclient import TestClient

from app.api import metadata_routes
from app.main import app
from app.schemas.metadata import (
    MetadataBusinessTerm,
    MetadataColumn,
    MetadataJoin,
    MetadataMetric,
    MetadataOverview,
    MetadataQuestionExample,
    MetadataTable,
    MetadataTableDetail,
)


class FakeMetadataCatalog:
    def overview(self) -> MetadataOverview:
        return MetadataOverview(
            table_count=2,
            column_count=8,
            metric_count=1,
            term_count=1,
            join_count=1,
        )

    def list_tables(self, search: str | None = None) -> list[MetadataTable]:
        return [
            MetadataTable(
                schema_name="mart",
                table_name="customer_info",
                display_name="Customer",
                domain="customer",
                description="Customer master",
                column_count=2,
            )
        ]

    def get_table(self, table_name: str) -> MetadataTableDetail | None:
        if table_name != "customer_info":
            return None
        return MetadataTableDetail(
            schema_name="mart",
            table_name=table_name,
            display_name="Customer",
            domain="customer",
            description="Customer master",
            columns=[
                MetadataColumn(
                    schema_name="mart",
                    table_name=table_name,
                    column_name="customer_no",
                    display_name="Customer number",
                    data_type="text",
                    description="Masked business identifier",
                )
            ],
        )

    def list_metrics(self, search: str | None = None) -> list[MetadataMetric]:
        return [
            MetadataMetric(
                metric_code="customer_count",
                metric_name="Customer count",
                description="Count of customers",
                formula="count(*)",
            )
        ]

    def list_terms(self, search: str | None = None) -> list[MetadataBusinessTerm]:
        return [MetadataBusinessTerm(term="active customer", definition="Active status customer")]

    def list_joins(self) -> list[MetadataJoin]:
        return [
            MetadataJoin(
                left_schema="mart",
                left_table="customer_info",
                left_column="customer_id",
                right_schema="mart",
                right_table="customer_asset_daily",
                right_column="customer_id",
                relationship_type="one_to_many",
                description="Customer assets",
            )
        ]

    def list_examples(self, limit: int = 30) -> list[MetadataQuestionExample]:
        return [
            MetadataQuestionExample(
                question="How many customers?",
                difficulty="simple",
                scenario="test",
            )
        ]


def test_metadata_routes_expose_catalog_and_unknown_table_is_404(monkeypatch) -> None:
    monkeypatch.setattr(metadata_routes, "MetadataCatalogService", FakeMetadataCatalog)
    client = TestClient(app)

    assert client.get("/api/metadata/overview").json()["table_count"] == 2
    assert client.get("/api/metadata/tables").json()[0]["table_name"] == "customer_info"
    table_detail = client.get("/api/metadata/tables/customer_info").json()
    assert table_detail["columns"][0]["column_name"] == "customer_no"
    assert client.get("/api/metadata/metrics").json()[0]["metric_code"] == "customer_count"
    assert client.get("/api/metadata/terms").json()[0]["term"] == "active customer"
    assert client.get("/api/metadata/joins").json()[0]["relationship_type"] == "one_to_many"
    assert client.get("/api/metadata/examples").json()[0]["difficulty"] == "simple"
    assert client.get("/api/metadata/tables/missing").status_code == 404
