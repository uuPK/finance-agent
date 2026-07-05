from app.core.config import get_settings
from app.llm.client import build_llm_client
from app.llm.schemas import LLMMessage, LLMRequest, LLMResponse


class LLMService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = build_llm_client(self.settings)

    def status(self) -> dict[str, str | bool | int]:
        return {
            "provider": self.settings.llm_provider,
            "model": self.settings.llm_model,
            "base_url": self.settings.llm_base_url,
            "timeout_seconds": self.settings.llm_timeout_seconds,
            "api_key_configured": bool(self.settings.active_llm_api_key),
        }

    async def complete(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        return await self.client.complete(
            LLMRequest(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        )
