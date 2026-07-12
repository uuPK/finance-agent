from app.core.config import Settings
from app.llm.client import OpenAICompatibleClient, build_llm_client


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
