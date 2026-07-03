from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Finance Agent"
    environment: str = "local"
    database_url: str = (
        "postgresql+psycopg://finance_agent:finance_agent@localhost:5432/finance_agent"
    )
    openai_api_key: str = ""
    model_name: str = "gpt-4.1-mini"
    max_retry: int = 2
    sql_timeout_seconds: int = 30
    max_result_rows: int = 1000
    backend_cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.backend_cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
