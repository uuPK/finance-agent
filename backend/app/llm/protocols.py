from typing import Protocol

from app.llm.schemas import LLMMessage, LLMResponse


class SupportsLLMComplete(Protocol):
    async def complete(
        self,
        messages: list[LLMMessage],
        temperature: float = 0.0,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> LLMResponse:
        raise NotImplementedError
