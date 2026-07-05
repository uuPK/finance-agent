from typing import Literal

from pydantic import BaseModel, Field


LLMRole = Literal["system", "user", "assistant"]


class LLMMessage(BaseModel):
    role: LLMRole
    content: str


class LLMUsage(BaseModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class LLMRequest(BaseModel):
    messages: list[LLMMessage]
    model: str | None = None
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    response_format: dict | None = None


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: LLMUsage | None = None
    raw: dict | None = None
