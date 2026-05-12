"""Groq provider — OpenAI-compatible chat completions。"""

from __future__ import annotations

import logging
import ssl
import time

import httpx

from app.providers.base import GenerationRequest, GenerationResponse, LLMProvider

log = logging.getLogger(__name__)


GROQ_BASE_URL = "https://api.groq.com/openai/v1"


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
            "model": self.default_model,
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
                r = await client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
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
