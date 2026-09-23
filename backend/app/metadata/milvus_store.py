"""Milvus collection with native BM25 and Zhipu-generated dense vectors."""

from __future__ import annotations

from typing import Any

from app.metadata.documents import MetadataDocument
from app.metadata.zhipu_retrieval import EmbedderProtocol


class MilvusMetadataStore:
    def __init__(
        self,
        uri: str,
        collection: str,
        dimensions: int,
        embedder: EmbedderProtocol,
        embedding_model: str,
        client: Any | None = None,
    ) -> None:
        self._owns_client = client is None
        if client is None:
            from pymilvus import MilvusClient

            client = MilvusClient(uri=uri, timeout=20)
        self.client = client
        self.collection = f"{collection}_{dimensions}"
        self.dimensions = dimensions
        self.embedder = embedder
        self.embedding_model = embedding_model

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def ensure_collection(self) -> None:
        if self.client.has_collection(self.collection):
            self.client.load_collection(self.collection)
            return
        from pymilvus import DataType, Function, FunctionType

        schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
        schema.add_field("doc_id", DataType.VARCHAR, is_primary=True, max_length=512)
        schema.add_field("doc_type", DataType.VARCHAR, max_length=32)
        schema.add_field("domain", DataType.VARCHAR, max_length=64)
        schema.add_field("entity", DataType.VARCHAR, max_length=64)
        schema.add_field("title", DataType.VARCHAR, max_length=1024)
        schema.add_field("content_hash", DataType.VARCHAR, max_length=64)
        schema.add_field(
            "search_text",
            DataType.VARCHAR,
            max_length=8192,
            enable_analyzer=True,
            analyzer_params={"type": "chinese"},
        )
        schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_field("dense", DataType.FLOAT_VECTOR, dim=self.dimensions)
        schema.add_function(
            Function(
                name="metadata_bm25",
                input_field_names=["search_text"],
                output_field_names=["sparse"],
                function_type=FunctionType.BM25,
            )
        )
        indexes = self.client.prepare_index_params()
        indexes.add_index(
            field_name="sparse", index_type="SPARSE_INVERTED_INDEX", metric_type="BM25"
        )
        indexes.add_index(field_name="dense", index_type="AUTOINDEX", metric_type="COSINE")
        self.client.create_collection(
            collection_name=self.collection,
            schema=schema,
            index_params=indexes,
            consistency_level="Strong",
        )
        self.client.load_collection(self.collection)

    def sync(self, documents: list[MetadataDocument]) -> dict[str, int]:
        """Upsert changed documents, delete stale IDs; never embed unchanged content."""
        self.ensure_collection()
        existing_rows = self.client.query(
            collection_name=self.collection,
            filter="",
            output_fields=["doc_id", "content_hash"],
            limit=16384,
        )
        if len(existing_rows) >= 16384:
            raise RuntimeError("Milvus metadata corpus exceeds the sync query limit")
        existing = {str(row["doc_id"]): str(row["content_hash"]) for row in existing_rows}
        desired = {doc.doc_id: doc for doc in documents}
        if len(desired) != len(documents):
            raise ValueError("Duplicate metadata document ID")
        stale = sorted(set(existing) - set(desired))
        for start in range(0, len(stale), 128):
            self.client.delete(collection_name=self.collection, ids=stale[start : start + 128])
        changed = [
            doc
            for doc in documents
            if existing.get(doc.doc_id) != doc.content_hash(self.embedding_model)
        ]
        for start in range(0, len(changed), 32):
            batch = changed[start : start + 32]
            vectors = self.embedder.embed([doc.search_text for doc in batch])
            if len(vectors) != len(batch):
                raise ValueError("Embedding batch count mismatch")
            for vector in vectors:
                if len(vector) != self.dimensions:
                    raise ValueError("Embedding vector dimension does not match Milvus schema")
            self.client.upsert(
                collection_name=self.collection,
                data=[
                    {
                        "doc_id": doc.doc_id,
                        "doc_type": doc.doc_type,
                        "domain": doc.domain,
                        "entity": doc.entity,
                        "title": doc.title,
                        "content_hash": doc.content_hash(self.embedding_model),
                        "search_text": doc.search_text,
                        "dense": vector,
                    }
                    for doc, vector in zip(batch, vectors, strict=True)
                ],
            )
        return {"total": len(documents), "upserted": len(changed), "deleted": len(stale)}

    def _search(
        self,
        data: list[str] | list[list[float]],
        anns_field: str,
        metric_type: str,
        limit: int,
        expression: str | None,
    ) -> list[str]:
        def run(filter_expression: str | None) -> list[str]:
            result = self.client.search(
                collection_name=self.collection,
                data=data,
                anns_field=anns_field,
                search_params={"metric_type": metric_type, "params": {}},
                filter=filter_expression or "",
                limit=limit,
                output_fields=["doc_id"],
            )
            return [
                str(hit.get("entity", {}).get("doc_id", hit.get("id")))
                for hit in result[0]
            ]

        filtered = run(expression)
        if not expression or len(filtered) >= limit:
            return filtered
        # Filter is only candidate narrowing.  Recover recall from the whole collection.
        return list(dict.fromkeys(filtered + run(None)))[:limit]

    def search_bm25(self, query: str, limit: int, expression: str | None = None) -> list[str]:
        return self._search([query], "sparse", "BM25", limit, expression)

    def search_dense(self, query: str, limit: int, expression: str | None = None) -> list[str]:
        vector = self.embedder.embed([query])[0]
        if len(vector) != self.dimensions:
            raise ValueError("Query embedding vector dimension does not match Milvus schema")
        return self._search([vector], "dense", "COSINE", limit, expression)
