"""Rank fusion and explainable evidence for hybrid metadata retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import zip_longest
from typing import Literal


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


FusionMode = Literal["bm25", "dense", "round_robin", "rrf"]


def rank_candidates(
    bm25_ids: list[str], dense_ids: list[str], mode: FusionMode
) -> list[RetrievalEvidence]:
    """Return genuinely different channel arms; only the RRF arm computes RRF."""
    if mode == "rrf":
        return reciprocal_rank_fusion(bm25_ids, dense_ids)
    if mode not in {"bm25", "dense", "round_robin"}:
        raise ValueError(f"Unsupported metadata fusion mode: {mode}")
    evidence: dict[str, RetrievalEvidence] = {}
    for channel, ids in (("bm25", bm25_ids), ("dense", dense_ids)):
        for rank, doc_id in enumerate(dict.fromkeys(ids), start=1):
            item = evidence.setdefault(doc_id, RetrievalEvidence(doc_id=doc_id))
            setattr(item, f"{channel}_rank", rank)
    if mode == "bm25":
        return [evidence[doc_id] for doc_id in dict.fromkeys(bm25_ids)]
    if mode == "dense":
        return [evidence[doc_id] for doc_id in dict.fromkeys(dense_ids)]
    ordered: list[RetrievalEvidence] = []
    seen: set[str] = set()
    for bm25_id, dense_id in zip_longest(bm25_ids, dense_ids):
        for doc_id in (bm25_id, dense_id):
            if doc_id is not None and doc_id not in seen:
                ordered.append(evidence[doc_id])
                seen.add(doc_id)
    return ordered
