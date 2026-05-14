"""Groq 429 / 5xx 退避重試邏輯測試。

不打網路：用 fake response 直接餵 helper，用 monkeypatch + counter 模擬 client.post。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from app.providers.groq import _is_retryable, _parse_retry_delay, _post_with_retry


# ──────────────────────────────────────────────────────────────────────────
# _parse_retry_delay
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class _FakeResponse:
    status_code: int = 429
    text: str = ""
    headers: dict[str, str] = field(default_factory=dict)


def test_parse_retry_delay_from_header():
    r = _FakeResponse(headers={"retry-after": "5"})
    delay = _parse_retry_delay(r, attempt=0)
    # 5 + 0.3 jitter
    assert 4.9 < delay < 5.5


def test_parse_retry_delay_from_body():
    r = _FakeResponse(
        text='{"error":{"message":"Please try again in 8.36s."}}'
    )
    delay = _parse_retry_delay(r, attempt=0)
    assert 8.5 < delay < 9.0


def test_parse_retry_delay_falls_back_to_exponential():
    r = _FakeResponse()  # 沒 header 也沒 hint
    assert _parse_retry_delay(r, attempt=0) == 1.0
    assert _parse_retry_delay(r, attempt=1) == 2.0
    assert _parse_retry_delay(r, attempt=2) == 4.0


def test_parse_retry_delay_header_takes_priority():
    """header 有就用 header，不去 parse body。"""
    r = _FakeResponse(
        headers={"retry-after": "3"},
        text="try again in 60s",
    )
    delay = _parse_retry_delay(r, attempt=0)
    assert delay < 4  # 用 header 的 3、不是 body 的 60


# ──────────────────────────────────────────────────────────────────────────
# _is_retryable
# ──────────────────────────────────────────────────────────────────────────


def test_is_retryable_429():
    assert _is_retryable(429) is True


def test_is_retryable_5xx():
    assert _is_retryable(500) is True
    assert _is_retryable(502) is True
    assert _is_retryable(599) is True


def test_is_retryable_2xx_4xx_no():
    assert _is_retryable(200) is False
    assert _is_retryable(400) is False
    assert _is_retryable(401) is False
    assert _is_retryable(404) is False


# ──────────────────────────────────────────────────────────────────────────
# _post_with_retry
# ──────────────────────────────────────────────────────────────────────────


class _FakeClient:
    """記錄 post 次數的假 client。每次回傳隊列中的下一個 response。"""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def post(self, url: str, *, headers: dict, json: Any) -> _FakeResponse:  # noqa: ARG002
        self.calls += 1
        if not self._responses:
            raise AssertionError("Fake client out of responses")
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """跳過實際 sleep，讓測試秒過。"""
    import app.providers.groq as g

    async def _instant(_seconds):
        return None

    monkeypatch.setattr(g.asyncio, "sleep", _instant)


async def test_post_with_retry_succeeds_on_first_try():
    client = _FakeClient([_FakeResponse(status_code=200)])
    r = await _post_with_retry(
        client,  # type: ignore[arg-type]
        "http://x",
        headers={},
        payload={},
        max_attempts=3,
        max_delay_s=15.0,
    )
    assert r.status_code == 200
    assert client.calls == 1


async def test_post_with_retry_recovers_after_429():
    client = _FakeClient(
        [
            _FakeResponse(status_code=429, headers={"retry-after": "1"}),
            _FakeResponse(status_code=429, headers={"retry-after": "1"}),
            _FakeResponse(status_code=200),
        ]
    )
    r = await _post_with_retry(
        client,  # type: ignore[arg-type]
        "http://x",
        headers={},
        payload={},
        max_attempts=3,
        max_delay_s=15.0,
    )
    assert r.status_code == 200
    assert client.calls == 3


async def test_post_with_retry_gives_up_after_max_attempts():
    client = _FakeClient(
        [
            _FakeResponse(status_code=429, headers={"retry-after": "1"}),
            _FakeResponse(status_code=429, headers={"retry-after": "1"}),
            _FakeResponse(status_code=429, headers={"retry-after": "1"}),
        ]
    )
    r = await _post_with_retry(
        client,  # type: ignore[arg-type]
        "http://x",
        headers={},
        payload={},
        max_attempts=3,
        max_delay_s=15.0,
    )
    assert r.status_code == 429
    assert client.calls == 3  # 不超出 max_attempts


async def test_post_with_retry_does_not_retry_on_4xx_other():
    """401 / 404 等不重試。"""
    client = _FakeClient([_FakeResponse(status_code=401)])
    r = await _post_with_retry(
        client,  # type: ignore[arg-type]
        "http://x",
        headers={},
        payload={},
        max_attempts=3,
        max_delay_s=15.0,
    )
    assert r.status_code == 401
    assert client.calls == 1


async def test_post_with_retry_5xx_retries():
    client = _FakeClient(
        [
            _FakeResponse(status_code=503),
            _FakeResponse(status_code=200),
        ]
    )
    r = await _post_with_retry(
        client,  # type: ignore[arg-type]
        "http://x",
        headers={},
        payload={},
        max_attempts=3,
        max_delay_s=15.0,
    )
    assert r.status_code == 200
    assert client.calls == 2


async def test_post_with_retry_respects_max_delay_cap(monkeypatch):
    """retry-after 給 60s 但 max_delay_s=5；應該 sleep 不超過 5。"""
    import app.providers.groq as g

    captured: list[float] = []

    async def _capture(seconds):
        captured.append(seconds)

    monkeypatch.setattr(g.asyncio, "sleep", _capture)

    client = _FakeClient(
        [
            _FakeResponse(status_code=429, headers={"retry-after": "60"}),
            _FakeResponse(status_code=200),
        ]
    )
    await _post_with_retry(
        client,  # type: ignore[arg-type]
        "http://x",
        headers={},
        payload={},
        max_attempts=3,
        max_delay_s=5.0,
    )
    assert captured == [5.0]
