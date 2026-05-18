"""Phase 6 M1 — GenerationRequest.model 覆寫機制驗證。

Phase A planner 用 70B、judge 用 8B，需要 per-request 指定 model。
測 MockProvider 的 echo 行為，避免實際打 Groq。
"""

from __future__ import annotations

from app.providers.base import GenerationRequest
from app.providers.mock import MockProvider


async def test_request_model_field_defaults_to_none():
    req = GenerationRequest(messages=[{"role": "user", "content": "hi"}])
    assert req.model is None


async def test_mock_provider_echoes_default_when_no_override():
    provider = MockProvider()
    req = GenerationRequest(messages=[{"role": "user", "content": "hi"}])
    resp = await provider.generate(req)
    assert resp.model == "mock-v1"


async def test_mock_provider_echoes_requested_model():
    """指定 model 時，回傳的 model 名稱要對得上 — 確認 routing 真的有生效。"""
    provider = MockProvider()
    req = GenerationRequest(
        messages=[{"role": "user", "content": "hi"}],
        model="llama-3.3-70b-versatile",
    )
    resp = await provider.generate(req)
    assert resp.model == "llama-3.3-70b-versatile"
