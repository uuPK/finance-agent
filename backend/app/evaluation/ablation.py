"""Frozen evaluation-only ablation arms; production defaults remain unchanged."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Literal

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core.config import Settings

CriticMode = Literal["none", "always", "conditional"]
PlanMode = Literal["structured", "direct"]


@dataclass(frozen=True, slots=True)
class AblationProfile:
    name: str
    retriever_mode: Literal["legacy", "hybrid"]
    fusion_mode: Literal["bm25", "dense", "round_robin", "rrf"] = "rrf"
    reranker: bool = False
    plan_mode: PlanMode = "structured"
    critic_mode: CriticMode = "always"

    def settings(self, baseline: Settings) -> Settings:
        return baseline.model_copy(
            update={
                "retriever_mode": self.retriever_mode,
                "retrieval_fusion_mode": self.fusion_mode,
                "enable_reranker": self.reranker,
                "ablation_strict_retrieval": True,
            }
        )


PROFILES: dict[str, AblationProfile] = {
    "full": AblationProfile("full", "hybrid", reranker=True),
    "no_query_plan": AblationProfile("no_query_plan", "hybrid", reranker=True, plan_mode="direct"),
    "no_critic": AblationProfile("no_critic", "hybrid", reranker=True, critic_mode="none"),
    "bm25_only": AblationProfile("bm25_only", "hybrid", fusion_mode="bm25"),
    "dense_only": AblationProfile("dense_only", "hybrid", fusion_mode="dense"),
    "bm25_dense": AblationProfile("bm25_dense", "hybrid", fusion_mode="round_robin"),
    "bm25_dense_rrf": AblationProfile("bm25_dense_rrf", "hybrid"),
    "full_cross_encoder": AblationProfile("full_cross_encoder", "hybrid", reranker=True),
    "legacy_retrieval": AblationProfile("legacy_retrieval", "legacy"),
    "hybrid_retrieval": AblationProfile("hybrid_retrieval", "hybrid"),
    "critic_always": AblationProfile("critic_always", "hybrid", reranker=True),
    "critic_conditional": AblationProfile(
        "critic_conditional", "hybrid", reranker=True, critic_mode="conditional"
    ),
}


def get_profile(name: str, critic_mode: CriticMode | None = None) -> AblationProfile:
    try:
        profile = PROFILES[name]
    except KeyError as exc:
        raise ValueError(f"Unknown ablation profile: {name}") from exc
    if critic_mode is None:
        return profile
    if name == "no_critic" and critic_mode != "none":
        raise ValueError("no_critic cannot be combined with a non-none critic mode")
    return AblationProfile(
        profile.name,
        profile.retriever_mode,
        profile.fusion_mode,
        profile.reranker,
        profile.plan_mode,
        critic_mode,
    )


def database_fingerprint(engine: Engine) -> str:
    """Hash mart and metadata base-table contents, not their approximate sizes."""
    digest = sha256()
    with engine.connect() as connection:
        names = connection.execute(
            text("""
            select table_schema, table_name from information_schema.tables
            where table_schema in ('mart', 'metadata') and table_type = 'BASE TABLE'
              and not (table_schema = 'metadata' and table_name = 'metadata_candidates')
            order by table_schema, table_name
        """)
        ).all()
        if not names:
            raise ValueError("No mart/metadata tables exist for ablation snapshot.")
        for schema, table in names:
            if not re.fullmatch(r"[a-z][a-z0-9_]*", schema) or not re.fullmatch(
                r"[a-z][a-z0-9_]*", table
            ):
                raise ValueError("Unsafe identifier in snapshot inventory.")
            digest.update(f"{schema}.{table}\n".encode())
            result = connection.execution_options(stream_results=True).execute(
                text(
                    f"select row_to_json(t)::text from {schema}.{table} t "
                    "order by row_to_json(t)::text"
                )
            )
            for row in result:
                digest.update(row[0].encode("utf-8"))
                digest.update(b"\n")
    return digest.hexdigest()


def validate_ablation_environment(
    engine: Engine, settings: Settings, profile: AblationProfile
) -> None:
    if not settings.active_llm_api_key:
        raise ValueError("The configured SQL/plan model API key is missing.")
    if profile.retriever_mode != "hybrid":
        return
    from app.metadata.documents import load_metadata_documents
    from app.metadata.hybrid_retriever import HybridMetadataRetriever

    if not (settings.zhipu_retrieval_api_key or settings.zhipu_api_key):
        raise ValueError("Zhipu retrieval API key is missing.")
    with engine.connect() as connection:
        retriever = HybridMetadataRetriever(connection, profile.settings(settings))
        try:
            retriever.store.verify_synced(load_metadata_documents(connection))
        finally:
            retriever.close()


def comparison_manifest(
    settings: Settings, cases: list[dict], snapshot: str, retry_budget: int
) -> dict[str, object]:
    """Fields that must match across arms; profile switches are intentionally excluded."""
    case_payload = [
        {
            key: str(case[key]) if key == "case_id" else case.get(key)
            for key in (
                "case_id",
                "case_code",
                "question",
                "difficulty",
                "source_type",
                "expected_status",
                "expected_query_plan",
                "expected_sql",
                "expected_result",
                "scoring_config",
                "tags",
            )
        }
        for case in cases
    ]
    case_hash = sha256(
        json.dumps(case_payload, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()
    root = Path(__file__).resolve().parents[1]
    prompt_files = [
        root / "agents" / name
        for name in (
            "llm_query_plan_actor.py",
            "llm_sql_actor.py",
            "llm_plan_critic.py",
            "llm_sql_critic.py",
            "llm_result_critic.py",
        )
    ]
    prompt_files.extend([
        root / "context" / "models.py",
        root / "context" / "builder.py",
    ])
    prompt_hash = sha256(b"".join(path.read_bytes() for path in prompt_files)).hexdigest()
    return {
        "manifest_version": 1,
        "model_provider": settings.llm_provider,
        "model": settings.llm_model,
        "endpoint_sha256": sha256(
            json.dumps(
                [settings.llm_base_url, settings.zhipu_base_url,
                 settings.milvus_uri, settings.milvus_collection],
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
        "embedding_model": settings.zhipu_embedding_model,
        "embedding_dimensions": settings.zhipu_embedding_dimensions,
        "rerank_model": settings.zhipu_rerank_model,
        "prompt_code_sha256": prompt_hash,
        "database_sha256": snapshot,
        "cases_sha256": case_hash,
        "case_count": len(cases),
        "retry_budget": retry_budget,
        "execution_retry_budget": settings.sql_execution_retry_limit,
        "stage_retrieval_budget": settings.stage_retrieval_budget,
        "global_retrieval_budget": settings.global_retrieval_budget,
        "metadata_refresh_budget": settings.metadata_refresh_limit,
        "temperature": 0.0,
    }
