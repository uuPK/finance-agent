"""Bounded, type-specific metadata lookup when hybrid retrieval is unavailable."""

from __future__ import annotations

import re

from sqlalchemy.engine import Connection

from app.metadata.documents import MetadataDocument, load_metadata_documents
from app.metadata.retriever import MetadataRetrievalResult
from app.schemas.v2_protocol import MissingContextRequest


def legacy_targeted_retrieval(
    connection: Connection, request: MissingContextRequest
) -> MetadataRetrievalResult:
    """Fallback for a requested type, not a repeat of the original broad query."""
    documents = load_metadata_documents(connection)
    kind = "join" if request.type == "join_path" else request.type
    words = [word.lower() for word in re.findall(r"[\w]+", request.concept) if len(word) > 1]

    def matches(doc: MetadataDocument) -> bool:
        if doc.doc_type != kind:
            return False
        row = doc.metadata
        if kind == "column" and request.from_table:
            return row.get("table_name") == request.from_table
        if kind == "join":
            endpoints = {row.get("left_table"), row.get("right_table")}
            return all(
                table in endpoints for table in (request.from_table, request.to_table) if table
            )
        return True

    candidates = [doc for doc in documents if matches(doc)]

    def score(doc: MetadataDocument) -> tuple[int, str]:
        haystack = doc.search_text.lower()
        value = sum(1 for word in words if word in haystack)
        if request.concept.lower() in haystack:
            value += 3
        return -value, doc.doc_id

    ranked = sorted(candidates, key=score)[:3]
    by_id = {doc.doc_id: doc for doc in documents}
    selected: dict[str, MetadataDocument] = {doc.doc_id: doc for doc in ranked}

    def include_table(schema: str, name: str) -> None:
        doc_id = f"table:{schema}.{name}"
        if doc_id in by_id:
            selected[doc_id] = by_id[doc_id]

    for doc in ranked:
        row = doc.metadata
        if doc.doc_type == "column":
            include_table(str(row["schema_name"]), str(row["table_name"]))
        elif doc.doc_type == "join":
            include_table(str(row["left_schema"]), str(row["left_table"]))
            include_table(str(row["right_schema"]), str(row["right_table"]))
        elif doc.doc_type == "metric":
            for table in row.get("source_tables") or []:
                include_table("mart", str(table))
    grouped: dict[str, list[dict]] = {
        item: [] for item in ("table", "column", "metric", "business_term", "join", "example")
    }
    for doc in selected.values():
        grouped[doc.doc_type].append(doc.metadata)
    return MetadataRetrievalResult(
        keywords=words,
        table_names=[str(row["table_name"]) for row in grouped["table"]],
        metric_codes=[str(row["metric_code"]) for row in grouped["metric"]],
        business_terms=[str(row["term"]) for row in grouped["business_term"]],
        matched_tables=grouped["table"],
        matched_columns=grouped["column"],
        matched_metrics=grouped["metric"],
        matched_business_terms=grouped["business_term"],
        matched_join_relationships=grouped["join"],
        matched_question_examples=grouped["example"],
        confidence=0.5 if ranked else 0.0,
        strategy="targeted_structured_metadata",
        evidence=[{"doc_id": doc.doc_id, "selected_reason": "targeted_legacy"}
                  for doc in selected.values()],
    )
