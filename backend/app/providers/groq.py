"""Groq provider — OpenAI-compatible chat completions。

支援的容錯：
- 429 (rate limit)：讀 Retry-After header 或 message body 裡的「try again in Xs」，
  asyncio.sleep 後重試；最多 settings.groq_max_attempts 次。
- 5xx：等同 429 邏輯重試。
- 其他 4xx：直接拋出。
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
import time

import httpx

from app.config import settings
from app.providers.base import GenerationRequest, GenerationResponse, LLMProvider

log = logging.getLogger(__name__)


GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Groq 的限速訊息固定格式：「Please try again in 8.359999999s.」
_RETRY_AFTER_HINT_RE = re.compile(r"try again in\s+([\d.]+)\s*s", re.IGNORECASE)


def _build_ssl_verify(verify_ssl: bool):
    """企業網路常有 self-signed CA，優先用 OS 憑證庫；失敗才退到 httpx 預設或 False。"""
    if not verify_ssl:
        return False
    try:
        import truststore  # type: ignore

        ctx = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        return ctx
    except Exception:  # noqa: BLE001
        return True


def _parse_retry_delay(response: httpx.Response | object, attempt: int) -> float:
    """從 response 推算下一次重試前該 sleep 多久。

    優先順序：
    1. Retry-After header（純秒數）
    2. response body 含「try again in Xs」
    3. exponential backoff: 1 * 2^attempt（attempt 從 0 起算）
    """
    headers = getattr(response, "headers", {}) or {}
    ra = headers.get("retry-after") or headers.get("Retry-After")
    if ra:
        try:
            return float(ra) + 0.3  # 加一點 jitter 避免雷群
        except ValueError:
            pass

    try:
        body = getattr(response, "text", "") or ""
        m = _RETRY_AFTER_HINT_RE.search(body)
        if m:
            return float(m.group(1)) + 0.3
    except Exception:  # noqa: BLE001
        pass

    return float(1.0 * (2**attempt))


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
    """POST 並針對 429 / 5xx 自動退避重試。最後一次失敗仍回該 response。"""
    last_resp: httpx.Response | None = None
    for attempt in range(max_attempts):
        last_resp = await client.post(url, headers=headers, json=payload)
        if not _is_retryable(last_resp.status_code):
            return last_resp
        if attempt == max_attempts - 1:
            return last_resp
        delay = min(_parse_retry_delay(last_resp, attempt), max_delay_s)
        log.warning(
            "Groq %s on attempt %d/%d; sleeping %.1fs before retry",
            last_resp.status_code,
            attempt + 1,
            max_attempts,
            delay,
        )
        await asyncio.sleep(delay)
    assert last_resp is not None  # for type checker
    return last_resp


class GroqProvider(LLMProvider):
    name = "groq"

    def __init__(
        self,
        api_key: str,
        default_model: str = "llama-3.1-8b-instant",
        timeout_s: float = 30.0,
        verify_ssl: bool = True,
    ) -> None:
        if not api_key:
            raise ValueError("GroqProvider requires an API key")
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
                    f"{GROQ_BASE_URL}/chat/completions",
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
                "Groq API error %s: %s",
                e.response.status_code,
                e.response.text[:400],
            )
            raise
        except httpx.RequestError as e:
            log.error("Groq request failed: %s", e)
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
