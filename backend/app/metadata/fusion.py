"""Rank fusion and explainable evidence for hybrid metadata retrieval."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RetrievalEvidence:
    doc_id: str
    bm25_rank: int | None = None
    dense_rank: int | None = None
    rrf_score: float = 0.0
    reranker_score: float | None = None
    selected_reason: str = ""

    def to_dict(self) -> dict[str, str | int | float | None]:
        return {
            "doc_id": self.doc_id,
            "bm25_rank": self.bm25_rank,
            "dense_rank": self.dense_rank,
            "rrf_score": self.rrf_score,
            "reranker_score": self.reranker_score,
            "selected_reason": self.selected_reason,
        }


def reciprocal_rank_fusion(
    bm25_ids: list[str], dense_ids: list[str], k: int = 60
) -> list[RetrievalEvidence]:
    if k <= 0:
        raise ValueError("RRF k must be positive")
    evidence: dict[str, RetrievalEvidence] = {}
    for name, ranked_ids in (("bm25", bm25_ids), ("dense", dense_ids)):
        for rank, doc_id in enumerate(dict.fromkeys(ranked_ids), start=1):
            item = evidence.setdefault(doc_id, RetrievalEvidence(doc_id=doc_id))
            setattr(item, f"{name}_rank", rank)
            item.rrf_score += 1.0 / (k + rank)
    return sorted(evidence.values(), key=lambda item: (-item.rrf_score, item.doc_id))
