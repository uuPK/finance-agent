import asyncio

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
            "proxy_configured": bool(self.settings.llm_proxy_url),
        }

    async def complete(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        request = LLMRequest(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        last_error: Exception | None = None
        for attempt in range(self.settings.max_retry + 1):
            try:
                return await self.client.complete(request)
            except Exception as exc:
                last_error = exc
                if attempt < self.settings.max_retry:
                    await asyncio.sleep(0.4 * (2**attempt))
        assert last_error is not None
        raise last_error
