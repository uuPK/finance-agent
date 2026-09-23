"""One canonical PostgreSQL metadata corpus for Milvus BM25 and dense retrieval."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


@dataclass(frozen=True, slots=True)
class MetadataDocument:
    doc_id: str
    doc_type: str
    domain: str
    entity: str
    title: str
    content: str
    keywords: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def search_text(self) -> str:
        # Keep the BM25 input and embedding input identical.  Milvus VARCHAR is byte-limited.
        raw = "\n".join((self.title, self.content, " ".join(self.keywords)))
        encoded = raw.encode("utf-8")[:8000]
        return encoded.decode("utf-8", errors="ignore")

    def content_hash(self, embedding_model: str) -> str:
        value = f"{embedding_model}\0{self.search_text}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


_QUERIES = {
    "table": """
        select schema_name, table_name, display_name, domain, description, grain
        from metadata.table_metadata where is_active = true order by schema_name, table_name
    """,
    "column": """
        select schema_name, table_name, column_name, display_name, data_type,
               description, semantic_type, is_dimension, is_metric_source, is_sensitive
        from metadata.column_metadata where is_active = true
        order by schema_name, table_name, column_name
    """,
    "metric": """
        select metric_code, metric_name, description, formula, default_aggregation,
               grain, source_tables, required_filters
        from metadata.metric_metadata where is_active = true order by metric_code
    """,
    "business_term": """
        select term, definition, synonyms, default_plan_fragment, clarification_required
        from metadata.business_terms where is_active = true order by term
    """,
    "join": """
        select id, left_schema, left_table, left_column, right_schema, right_table,
               right_column, relationship_type, description
        from metadata.join_relationships where is_active = true order by id
    """,
    "example": """
        select id, question, difficulty, scenario, expected_sql, tags
        from metadata.question_examples where is_active = true order by id
    """,
    "rule": """
        select rule_code, rule_name, rule_type, config, severity, description
        from metadata.rule_constraints where is_active = true order by rule_code
    """,
}


def _value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _parts(*values: Any) -> str:
    return "；".join(part for value in values if (part := _value(value).strip()))


def _list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int))]


def load_metadata_documents(connection: Connection) -> list[MetadataDocument]:
    rows = {
        kind: [dict(row) for row in connection.execute(text(sql)).mappings()]
        for kind, sql in _QUERIES.items()
    }
    table_domains = {row["table_name"]: row["domain"] for row in rows["table"]}
    documents: list[MetadataDocument] = []
    for row in rows["table"]:
        name = str(row["table_name"])
        documents.append(
            MetadataDocument(
                doc_id=f"table:{row['schema_name']}.{name}",
                doc_type="table",
                domain=str(row["domain"]),
                entity="customer" if "cust" in name else "",
                title=str(row["display_name"]),
                content=_parts(name, row["description"], row["grain"]),
                keywords=(name, str(row["domain"])),
                metadata=row,
            )
        )
    for row in rows["column"]:
        table = str(row["table_name"])
        column = str(row["column_name"])
        documents.append(
            MetadataDocument(
                doc_id=f"column:{row['schema_name']}.{table}.{column}",
                doc_type="column",
                domain=table_domains.get(table, ""),
                entity="customer" if "cust" in table else "",
                title=str(row["display_name"]),
                content=_parts(table, column, row["description"], row["semantic_type"]),
                keywords=(table, column, column.replace("_", " ")),
                metadata=row,
            )
        )
    for row in rows["metric"]:
        tables = _list(row.get("source_tables"))
        domain = next((table_domains[name] for name in tables if name in table_domains), "")
        documents.append(
            MetadataDocument(
                doc_id=f"metric:{row['metric_code']}",
                doc_type="metric",
                domain=domain,
                entity="customer" if any("cust" in name for name in tables) else "",
                title=str(row["metric_name"]),
                content=_parts(row["metric_code"], row["description"], row["formula"], tables),
                keywords=(str(row["metric_code"]), *tables),
                metadata=row,
            )
        )
    for row in rows["business_term"]:
        documents.append(
            MetadataDocument(
                doc_id=f"term:{row['term']}",
                doc_type="business_term",
                domain="",
                entity="",
                title=str(row["term"]),
                content=_parts(row["definition"], row["default_plan_fragment"]),
                keywords=tuple(_list(row.get("synonyms"))),
                metadata=row,
            )
        )
    for row in rows["join"]:
        left, right = str(row["left_table"]), str(row["right_table"])
        documents.append(
            MetadataDocument(
                doc_id=f"join:{row['id']}",
                doc_type="join",
                domain=table_domains.get(right, table_domains.get(left, "")),
                entity="customer" if "cust" in left or "cust" in right else "",
                title=f"{left} ↔ {right}",
                content=_parts(
                    row["description"], left, row["left_column"], right, row["right_column"]
                ),
                keywords=(left, right, str(row["left_column"]), str(row["right_column"])),
                metadata=row,
            )
        )
    for row in rows["example"]:
        documents.append(
            MetadataDocument(
                doc_id=f"example:{row['id']}",
                doc_type="example",
                domain="",
                entity="",
                title=str(row["question"]),
                content=_parts(row["question"], str(row["expected_sql"])[:900]),
                keywords=tuple(_list(row.get("tags"))),
                metadata=row,
            )
        )
    for row in rows["rule"]:
        documents.append(
            MetadataDocument(
                doc_id=f"rule:{row['rule_code']}",
                doc_type="rule",
                domain="",
                entity="",
                title=str(row["rule_name"]),
                content=_parts(row["description"], row["rule_type"], row["config"]),
                keywords=(str(row["rule_code"]),),
                metadata=row,
            )
        )
    return documents
