"""Cerebras provider — OpenAI-compatible chat completions。

Cerebras Cloud（https://cloud.cerebras.ai）對 free tier 提供 1M tokens/day、
~1800 tok/s 的推理（Wafer-Scale Engine）。免費 tier 模型常見選項：
  - gpt-oss-120b（推薦：OpenAI 開源、120B，能力佳）
  - llama-3.3-70b
  - llama3.1-8b
  - qwen-3-32b（中文友好）

可用清單以 https://cloud.cerebras.ai/?tab=models 顯示為準，Cerebras 會調整
（例如 qwen-3-235b-a22b-instruct-2507 曾下架）。預設 model 走 env var
`CEREBRAS_DEFAULT_MODEL`，被下架時改 env 就好。

API 路徑與 OpenAI 完全一致 —— /v1/chat/completions，只是 base_url 換掉、
回傳結構同 OpenAI；429 / 5xx 用 exponential backoff 重試。
"""

from __future__ import annotations

import asyncio
import logging
import ssl
import time

import httpx

from app.config import settings
from app.providers.base import GenerationRequest, GenerationResponse, LLMProvider

log = logging.getLogger(__name__)


CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"


def _build_ssl_verify(verify_ssl: bool):
    if not verify_ssl:
        return False
    try:
        import truststore  # type: ignore

        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return ctx
    except Exception:  # noqa: BLE001
        return True


def _is_retryable(status: int) -> bool:
    return status == 429 or 500 <= status < 600


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict,
    payload: dict,
    max_attempts: int,
    max_delay_s: float,
) -> httpx.Response:
    """OpenAI-style retry — Retry-After header 優先；否則 exponential backoff。"""
    last_resp: httpx.Response | None = None
    for attempt in range(max_attempts):
        last_resp = await client.post(url, headers=headers, json=payload)
        if not _is_retryable(last_resp.status_code):
            return last_resp
        if attempt == max_attempts - 1:
            return last_resp

        # Retry-After 優先
        ra = last_resp.headers.get("retry-after") or last_resp.headers.get("Retry-After")
        delay: float
        if ra:
            try:
                delay = float(ra) + 0.3
            except ValueError:
                delay = 1.0 * (2**attempt)
        else:
            delay = 1.0 * (2**attempt)
        delay = min(delay, max_delay_s)
        log.warning(
            "Cerebras %s on attempt %d/%d; sleeping %.1fs before retry",
            last_resp.status_code,
            attempt + 1,
            max_attempts,
            delay,
        )
        await asyncio.sleep(delay)
    assert last_resp is not None
    return last_resp


class CerebrasProvider(LLMProvider):
    name = "cerebras"

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-oss-120b",
        timeout_s: float = 30.0,
        verify_ssl: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("CerebrasProvider requires an API key")
        self.api_key = api_key
        self.default_model = default_model
        self.timeout_s = timeout_s
        self.verify_ssl = verify_ssl

    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        messages: list[dict] = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.extend(req.messages)

        payload: dict = {
            "model": req.model or self.default_model,
            "messages": messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        if req.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        if req.logprobs:
            payload["logprobs"] = True
            if req.top_logprobs > 0:
                payload["top_logprobs"] = req.top_logprobs

        start = time.perf_counter()
        verify = _build_ssl_verify(self.verify_ssl)
        try:
            async with httpx.AsyncClient(timeout=self.timeout_s, verify=verify) as client:
                r = await _post_with_retry(
                    client,
                    f"{CEREBRAS_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    payload=payload,
                    max_attempts=settings.groq_max_attempts,
                    max_delay_s=settings.groq_max_retry_delay_s,
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            log.error(
                "Cerebras API error %s: %s",
                e.response.status_code,
                e.response.text[:400],
            )
            raise
        except httpx.RequestError as e:
            log.error("Cerebras request failed: %s", e)
            raise

        latency_ms = int((time.perf_counter() - start) * 1000)
        choice = data["choices"][0]
        message = choice["message"]
        usage = data.get("usage", {})

        logprobs_content: list[dict] | None = None
        raw_lp = choice.get("logprobs") or {}
        if raw_lp.get("content"):
            logprobs_content = [
                {
                    "token": item.get("token", ""),
                    "logprob": item.get("logprob", 0.0),
                    "top_logprobs": [
                        {"token": alt.get("token", ""), "logprob": alt.get("logprob", 0.0)}
                        for alt in (item.get("top_logprobs") or [])
                    ],
                }
                for item in raw_lp["content"]
            ]

        return GenerationResponse(
            text=(message.get("content") or "").strip(),
            model=data.get("model", self.default_model),
            usage={
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            },
            latency_ms=latency_ms,
            logprobs_content=logprobs_content,
        )
