import asyncio

from app.core.config import Settings
from app.llm.client import OpenAICompatibleClient, build_llm_client
from app.llm.schemas import LLMMessage, LLMResponse
from app.services.llm_service import LLMService


def test_build_deepseek_client_uses_configured_proxy() -> None:
    settings = Settings(
        _env_file=None,
        llm_provider="deepseek",
        llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-chat",
        llm_proxy_url="http://127.0.0.1:7890",
        deepseek_api_key="test-key",
    )

    client = build_llm_client(settings)

    assert isinstance(client, OpenAICompatibleClient)
    assert client.proxy_url == "http://127.0.0.1:7890"


class FlakyClient:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, request) -> LLMResponse:
        self.calls += 1
        if self.calls == 1:
            raise ConnectionError("temporary network failure")
        return LLMResponse(content="{}", model="test", provider="test")


def test_llm_service_retries_transient_failures() -> None:
    service = LLMService()
    service.settings = Settings(_env_file=None, max_retry=1)
    service.client = FlakyClient()

    response = asyncio.run(service.complete([LLMMessage(role="user", content="test")]))

    assert response.model == "test"
    assert service.client.calls == 2
