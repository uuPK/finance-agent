from abc import ABC, abstractmethod

from app.core.config import Settings, get_settings
from app.llm.schemas import LLMRequest, LLMResponse, LLMUsage


class LLMClientError(RuntimeError):
    pass


class BaseLLMClient(ABC):
    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError


class OpenAICompatibleClient(BaseLLMClient):
    def __init__(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout_seconds: int = 30,
        proxy_url: str | None = None,
    ) -> None:
        self.provider = provider
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self.proxy_url = proxy_url

    async def complete(self, request: LLMRequest) -> LLMResponse:
        try:
            import httpx
        except ImportError as exc:
            raise LLMClientError(
                "httpx is required for LLM calls. Install backend runtime dependencies first."
            ) from exc

        if not self.api_key:
            raise LLMClientError(f"{self.provider} API key is not configured.")

        payload = {
            "model": request.model or self.default_model,
            "messages": [message.model_dump() for message in request.messages],
            "temperature": request.temperature,
        }
        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens
        if request.response_format is not None:
            payload["response_format"] = request.response_format

        async with httpx.AsyncClient(
            timeout=self.timeout_seconds,
            proxy=self.proxy_url,
        ) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

        if response.status_code >= 400:
            raise LLMClientError(
                f"{self.provider} request failed with status {response.status_code}: "
                f"{response.text[:500]}"
            )

        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise LLMClientError(f"{self.provider} response contains no choices.")

        content = choices[0].get("message", {}).get("content")
        if content is None:
            raise LLMClientError(f"{self.provider} response contains no message content.")

        usage_data = data.get("usage")
        usage = LLMUsage(**usage_data) if isinstance(usage_data, dict) else None

        return LLMResponse(
            content=content,
            model=data.get("model") or payload["model"],
            provider=self.provider,
            usage=usage,
            raw=data,
        )


def build_llm_client(settings: Settings | None = None) -> BaseLLMClient:
    active_settings = settings or get_settings()
    provider = active_settings.llm_provider.lower()

    if provider == "deepseek":
        return OpenAICompatibleClient(
            provider="deepseek",
            api_key=active_settings.deepseek_api_key,
            base_url=active_settings.llm_base_url,
            default_model=active_settings.llm_model,
            timeout_seconds=active_settings.llm_timeout_seconds,
            proxy_url=active_settings.llm_proxy_url,
        )

    if provider == "openai":
        return OpenAICompatibleClient(
            provider="openai",
            api_key=active_settings.openai_api_key,
            base_url=active_settings.llm_base_url or "https://api.openai.com/v1",
            default_model=active_settings.llm_model,
            timeout_seconds=active_settings.llm_timeout_seconds,
            proxy_url=active_settings.llm_proxy_url,
        )

    raise LLMClientError(f"Unsupported LLM provider: {active_settings.llm_provider}")
