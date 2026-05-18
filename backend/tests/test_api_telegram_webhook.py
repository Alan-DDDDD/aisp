"""Phase 6 M7 — Telegram webhook endpoint 行為。"""

from __future__ import annotations

import pytest

from tests._api import api_ctx  # noqa: F401


@pytest.mark.asyncio
async def test_webhook_404_when_token_empty(api_ctx, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.config.settings.tg_bot_token", "")
    client, _ = api_ctx
    r = await client.post("/telegram/webhook", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_webhook_410_when_polling_mode(api_ctx, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.config.settings.tg_bot_token", "fake-token")
    monkeypatch.setattr("app.config.settings.tg_mode", "polling")
    client, _ = api_ctx
    r = await client.post("/telegram/webhook", json={})
    assert r.status_code == 410
    assert "polling" in r.text.lower()
