from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Finance Agent"
    environment: str = "local"
    database_url: str = (
        "postgresql+psycopg://finance_agent:finance_agent@localhost:5432/finance_agent"
    )
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-chat"
    llm_base_url: str = "https://api.deepseek.com"
    llm_timeout_seconds: int = 30
    llm_proxy_url: str | None = None
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    zhipu_api_key: str = ""
    zhipu_retrieval_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    zhipu_embedding_model: str = "embedding-3"
    zhipu_embedding_dimensions: int = 1024
    zhipu_rerank_model: str = "rerank"
    retriever_mode: str = "legacy"
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "finance_metadata_hybrid_v1"
    enable_reranker: bool = True
    retrieval_bm25_top_k: int = 30
    retrieval_dense_top_k: int = 30
    rerank_top_n: int = 30
    final_top_k: int = 16
    schema_context_budget: int = 10000
    stage_retrieval_budget: int = 2
    global_retrieval_budget: int = 3
    metadata_refresh_limit: int = 1
    sql_execution_retry_limit: int = 2
    sql_execution_backoff_ms: int = 200
    model_name: str = "deepseek-chat"
    max_retry: int = 2
    sql_timeout_seconds: int = 30
    empty_result_diagnostic_timeout_seconds: int = 3
    enable_sql_explain_check: bool = False
    sql_explain_timeout_seconds: int = 3
    sql_explain_max_plan_rows: int = 1_000_000
    sql_explain_max_total_cost: int = 1_000_000
    max_result_rows: int = 1000
    result_preview_rows: int = 100
    export_max_rows: int = 100000
    export_timeout_seconds: int = 60
    backend_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]

    @property
    def active_llm_api_key(self) -> str:
        if self.llm_provider.lower() == "deepseek":
            return self.deepseek_api_key
        return self.openai_api_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
