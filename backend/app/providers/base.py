from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field


class GenerationRequest(BaseModel):
    system: str = ""
    messages: list[dict[str, Any]] = Field(default_factory=list)
    temperature: float = 0.3
    max_tokens: int = 1024
    response_format: str | None = None  # "json" | None
    # 要求 provider 一併回傳 token-level logprobs（OpenAI-compatible logprobs.content）
    logprobs: bool = False
    top_logprobs: int = 0  # 每個 token 位置額外回多少個 alternatives（0=不要 alternatives）


class GenerationResponse(BaseModel):
    text: str
    model: str
    usage: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int = 0
    # OpenAI-compatible logprobs.content：每個輸出 token 的 logprob + 同位置 alternatives。
    # 結構：[{"token": str, "logprob": float, "top_logprobs": [{"token": str, "logprob": float}, ...]}]
    logprobs_content: list[dict[str, Any]] | None = None


class LLMProvider(ABC):
    name: str

    @abstractmethod
    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        raise NotImplementedError

    async def stream(self, req: GenerationRequest) -> AsyncIterator[str]:
        """Optional streaming. Phase 1 不要求所有 provider 都實作。"""
        resp = await self.generate(req)
        yield resp.text
