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
    deepseek_api_key: str = ""
    openai_api_key: str = ""
    model_name: str = "deepseek-chat"
    max_retry: int = 2
    sql_timeout_seconds: int = 30
    max_result_rows: int = 1000
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
