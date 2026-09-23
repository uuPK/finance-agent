"""Official Zhipu embedding and rerank HTTP contracts."""

from __future__ import annotations

from typing import Protocol

import httpx


class EmbedderProtocol(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class RerankerProtocol(Protocol):
    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]: ...


class ZhipuRetrievalClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://open.bigmodel.cn/api/paas/v4",
        embedding_model: str = "embedding-3",
        dimensions: int = 1024,
        rerank_model: str = "rerank",
        http_client: httpx.Client | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("ZHIPU_API_KEY is required for hybrid retrieval")
        if dimensions not in {256, 512, 1024, 2048}:
            raise ValueError("embedding-3 dimensions must be 256, 512, 1024 or 2048")
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.embedding_model = embedding_model
        self.dimensions = dimensions
        self.rerank_model = rerank_model
        self._owns_client = http_client is None
        self.http_client = http_client or httpx.Client(timeout=45)

    def close(self) -> None:
        if self._owns_client:
            self.http_client.close()

    def _post(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        request = {
            "headers": {"Authorization": f"Bearer {self.api_key}"},
            "json": payload,
        }
        response = self.http_client.post(f"{self.base_url}/{path}", **request)
        if response.is_error:
            raise RuntimeError(f"Zhipu {path} HTTP {response.status_code}")
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError(f"Zhipu {path} returned a non-object response")
        return data

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if len(texts) > 64:
            raise ValueError("embedding-3 accepts at most 64 texts per request")
        payload = self._post(
            "embeddings",
            {"model": self.embedding_model, "input": texts, "dimensions": self.dimensions},
        )
        items = payload.get("data")
        if not isinstance(items, list) or len(items) != len(texts):
            raise ValueError("Zhipu embedding response count differs from input count")
        vectors: list[list[float] | None] = [None] * len(texts)
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Zhipu embedding item is not an object")
            index, vector = item.get("index"), item.get("embedding")
            if not isinstance(index, int) or not 0 <= index < len(texts):
                raise ValueError("Zhipu embedding returned an invalid index")
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise ValueError("Zhipu embedding returned an unexpected vector dimension")
            if vectors[index] is not None:
                raise ValueError("Zhipu embedding returned a duplicate index")
            vectors[index] = [float(value) for value in vector]
        if any(vector is None for vector in vectors):
            raise ValueError("Zhipu embedding omitted an input index")
        return [vector for vector in vectors if vector is not None]

    def rerank(self, query: str, documents: list[str]) -> list[tuple[int, float]]:
        if not documents:
            return []
        if len(documents) > 128:
            raise ValueError("Zhipu rerank accepts at most 128 documents")
        payload = self._post(
            "rerank",
            {
                "model": self.rerank_model,
                "query": query[:4096],
                "documents": [document[:4096] for document in documents],
                "top_n": len(documents),
            },
        )
        items = payload.get("results")
        if not isinstance(items, list) or len(items) != len(documents):
            raise ValueError("Zhipu rerank response count differs from candidate count")
        ranking: list[tuple[int, float]] = []
        seen: set[int] = set()
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Zhipu rerank item is not an object")
            index = item.get("index")
            if not isinstance(index, int) or not 0 <= index < len(documents) or index in seen:
                raise ValueError("Zhipu rerank returned an invalid or duplicate index")
            seen.add(index)
            ranking.append((index, float(item["relevance_score"])))
        return sorted(ranking, key=lambda item: (-item[1], item[0]))
