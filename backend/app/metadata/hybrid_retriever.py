"""Query analysis -> soft filter -> Milvus BM25/Dense -> RRF -> Zhipu rerank."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from sqlalchemy.engine import Connection

from app.core.config import Settings
from app.metadata.documents import MetadataDocument, load_metadata_documents
from app.metadata.fusion import RetrievalEvidence, reciprocal_rank_fusion
from app.metadata.metadata_filter import candidate_filter
from app.metadata.milvus_store import MilvusMetadataStore
from app.metadata.query_analysis import analyze_query
from app.metadata.retriever import MetadataRetrievalResult
from app.metadata.zhipu_retrieval import RerankerProtocol, ZhipuRetrievalClient
from app.schemas.query_plan import QueryPlan

_FORMULA_COLUMN_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z][A-Za-z0-9_]*)\b")


class HybridMetadataRetriever:
    def __init__(
        self,
        connection: Connection,
        settings: Settings,
        store: MilvusMetadataStore | None = None,
        reranker: RerankerProtocol | None = None,
    ) -> None:
        self.connection = connection
        self.settings = settings
        if store is None or (settings.enable_reranker and reranker is None):
            zhipu = ZhipuRetrievalClient(
                api_key=settings.zhipu_retrieval_api_key or settings.zhipu_api_key,
                base_url=settings.zhipu_base_url,
                embedding_model=settings.zhipu_embedding_model,
                dimensions=settings.zhipu_embedding_dimensions,
                rerank_model=settings.zhipu_rerank_model,
            )
        else:
            zhipu = None
        self.store = store or MilvusMetadataStore(
            uri=settings.milvus_uri,
            collection=settings.milvus_collection,
            dimensions=settings.zhipu_embedding_dimensions,
            embedder=zhipu,  # type: ignore[arg-type]
            embedding_model=settings.zhipu_embedding_model,
        )
        self.reranker = reranker or zhipu
        self._zhipu = zhipu

    def close(self) -> None:
        try:
            if self._zhipu is not None:
                self._zhipu.close()
        finally:
            close = getattr(self.store, "close", None)
            if callable(close):
                close()

    def retrieve(
        self, question: str, query_plan: QueryPlan | None = None
    ) -> MetadataRetrievalResult:
        if not question.strip():
            raise ValueError("Hybrid retrieval requires a non-empty question")
        documents = load_metadata_documents(self.connection)
        if not documents:
            raise RuntimeError("No active metadata documents exist in PostgreSQL")
        by_id = {doc.doc_id: doc for doc in documents}
        analysis = analyze_query(question)
        expression = candidate_filter(analysis)
        index_sync = self.store.sync(documents)
        lexical_query = " ".join((analysis.rewritten_query, *analysis.keywords))[:4096]
        bm25_ids = self.store.search_bm25(
            lexical_query, self.settings.retrieval_bm25_top_k, expression
        )
        dense_ids = self.store.search_dense(
            analysis.rewritten_query, self.settings.retrieval_dense_top_k, expression
        )
        ranked = [
            item
            for item in reciprocal_rank_fusion(bm25_ids, dense_ids)
            if item.doc_id in by_id
        ]
        if not ranked:
            raise RuntimeError("Milvus returned no metadata candidates")
        candidate_limit = min(self.settings.rerank_top_n, 128)
        candidate_type_caps = {
            "table": 8,
            "column": 16,
            "metric": 10,
            "business_term": 6,
            "join": 8,
            "example": 6,
            "rule": 2,
        }
        candidate_counts = dict.fromkeys(candidate_type_caps, 0)
        candidates: list[RetrievalEvidence] = []
        for item in ranked:
            kind = by_id[item.doc_id].doc_type
            if candidate_counts[kind] >= candidate_type_caps[kind]:
                continue
            candidates.append(item)
            candidate_counts[kind] += 1
            if len(candidates) >= candidate_limit:
                break
        rerank_error: str | None = None
        if self.settings.enable_reranker:
            if self.reranker is None:
                raise RuntimeError("Reranker is enabled but no reranker is configured")
            try:
                scores = self.reranker.rerank(
                    analysis.rewritten_query,
                    [by_id[item.doc_id].search_text for item in candidates],
                )
                rescored = []
                for index, score in scores:
                    item = candidates[index]
                    item.reranker_score = score
                    rescored.append(item)
                candidates = rescored
            except Exception as exc:
                # Preserve availability while making degraded ranking observable.
                rerank_error = f"{type(exc).__name__}: {exc}"
        type_caps = {
            "table": 8,
            "column": 10,
            "metric": 6,
            "business_term": 4,
            "join": 5,
            "example": 3,
            "rule": 2,
        }
        type_counts = dict.fromkeys(type_caps, 0)
        selected: list[RetrievalEvidence] = []
        for item in candidates:
            kind = by_id[item.doc_id].doc_type
            if type_counts[kind] >= type_caps[kind]:
                continue
            selected.append(item)
            type_counts[kind] += 1
            if len(selected) >= self.settings.final_top_k:
                break
        for item in selected:
            channels = "+".join(
                name
                for name, rank in (("bm25", item.bm25_rank), ("dense", item.dense_rank))
                if rank is not None
            )
            item.selected_reason = (
                f"{channels} -> RRF -> rerank"
                if item.reranker_score is not None
                else f"{channels} -> RRF"
            )
        return self._materialize(
            documents,
            selected,
            analysis=asdict(analysis),
            expression=expression,
            index_sync=index_sync,
            query_plan=query_plan,
            rerank_error=rerank_error,
        )

    def _materialize(
        self,
        documents: list[MetadataDocument],
        selected: list[RetrievalEvidence],
        analysis: dict[str, Any],
        expression: str | None,
        index_sync: dict[str, int],
        query_plan: QueryPlan | None,
        rerank_error: str | None,
    ) -> MetadataRetrievalResult:
        by_id = {doc.doc_id: doc for doc in documents}
        selected_ids = {item.doc_id for item in selected}
        evidence = {item.doc_id: item for item in selected}

        def add(doc_id: str, reason: str) -> None:
            if doc_id in by_id and doc_id not in selected_ids:
                selected_ids.add(doc_id)
                evidence[doc_id] = RetrievalEvidence(doc_id=doc_id, selected_reason=reason)

        if query_plan is not None:
            for table in query_plan.data_requirements.candidate_tables:
                add(f"table:mart.{table}", "query_plan_anchor")
            for metric in query_plan.metrics:
                if metric.metric_code:
                    add(f"metric:{metric.metric_code}", "query_plan_anchor")

        # QueryAnalysis domains are hints, not exclusions.  Ground one physical table
        # per explicitly detected domain even when examples dominate rerank scores.
        for doc in documents:
            if doc.doc_type == "table" and doc.domain in analysis["domains"]:
                add(doc.doc_id, "query_domain_anchor")

        # Grounded dependency expansion: metrics/columns/joins need their physical tables.
        # Example SQL is advisory and must not widen the executable table allowlist.
        for doc_id in list(selected_ids):
            doc = by_id[doc_id]
            row = doc.metadata
            if doc.doc_type == "metric":
                for table in row.get("source_tables") or []:
                    add(f"table:mart.{table}", "metric_source_table")
                for table, column in _FORMULA_COLUMN_RE.findall(str(row.get("formula", ""))):
                    add(f"table:mart.{table}", "metric_formula_table")
                    add(f"column:mart.{table}.{column}", "metric_formula_column")
            elif doc.doc_type == "column":
                add(f"table:{row['schema_name']}.{row['table_name']}", "column_parent_table")
            elif doc.doc_type == "join":
                add(f"table:{row['left_schema']}.{row['left_table']}", "join_endpoint")
                add(f"table:{row['right_schema']}.{row['right_table']}", "join_endpoint")

        table_names = {
            str(by_id[doc_id].metadata["table_name"])
            for doc_id in selected_ids
            if by_id[doc_id].doc_type == "table"
        }
        if not table_names:
            raise RuntimeError("Hybrid retrieval selected no grounded physical tables")
        for doc in documents:
            if doc.doc_type != "join":
                continue
            row = doc.metadata
            if row["left_table"] in table_names and row["right_table"] in table_names:
                add(doc.doc_id, "join_path_closure")

        ordered_ids = [item.doc_id for item in selected]
        ordered_ids.extend(sorted(selected_ids - set(ordered_ids)))
        matched: dict[str, list[dict[str, Any]]] = {
            kind: []
            for kind in ("table", "column", "metric", "business_term", "join", "example", "rule")
        }
        for doc_id in ordered_ids:
            doc = by_id[doc_id]
            matched[doc.doc_type].append(doc.metadata)
        return MetadataRetrievalResult(
            keywords=list(analysis["keywords"]),
            table_names=list(dict.fromkeys(row["table_name"] for row in matched["table"])),
            metric_codes=list(dict.fromkeys(row["metric_code"] for row in matched["metric"])),
            business_terms=list(dict.fromkeys(row["term"] for row in matched["business_term"])),
            matched_tables=matched["table"],
            matched_columns=matched["column"],
            matched_metrics=matched["metric"],
            matched_business_terms=matched["business_term"],
            matched_join_relationships=matched["join"],
            matched_question_examples=matched["example"][:3],
            matched_rule_constraints=matched["rule"],
            confidence=0.8 if any(item.bm25_rank and item.dense_rank for item in selected) else 0.5,
            strategy=(
                "milvus_bm25_dense_rrf_rerank"
                if self.settings.enable_reranker and not rerank_error
                else "milvus_bm25_dense_rrf"
            ),
            evidence=[evidence[doc_id].to_dict() for doc_id in ordered_ids],
            query_analysis=analysis,
            metadata_filter=expression,
            index_sync=index_sync,
            fallback_reason=rerank_error,
        )
