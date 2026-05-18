"""Telegram webhook 入口（PLAN §22.4.4 / §22.5.7）。

兩種模式：
  - polling：PtbBot 自己拉 Telegram，這個 endpoint 永遠回 410（明示已關閉）
  - webhook：Telegram 把 update POST 過來，丟給 Application 的 update_queue

部署 webhook：
  1. 把 server 用 HTTPS 公開出去（ngrok / Cloudflare Tunnel / 真實 domain）
  2. curl 'https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your>/telegram/webhook'
  3. 設定 TG_MODE=webhook
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.config import settings
from app.synthesis import integration

log = logging.getLogger(__name__)


router = APIRouter(tags=["telegram"])


@router.post("/telegram/webhook")
async def telegram_webhook(request: Request) -> dict:
    if not settings.tg_bot_token:
        raise HTTPException(404, "Telegram 整套停用（TG_BOT_TOKEN 空）")
    if settings.tg_mode != "webhook":
        raise HTTPException(
            410,
            f"Telegram bot 目前運行於 {settings.tg_mode} 模式；webhook endpoint 已關閉。"
            " 請改設 TG_MODE=webhook 並重啟。",
        )

    try:
        from telegram import Update  # type: ignore
    except ImportError as e:
        raise HTTPException(500, f"python-telegram-bot 未安裝：{e}") from e

    bot = integration.get_bot()
    # PtbBot 內部 Application；用 getattr 避開 type-checker 對抽象的抱怨
    app_obj = getattr(bot, "_app", None)
    if app_obj is None:
        raise HTTPException(503, "Telegram bot 尚未初始化")

    payload = await request.json()
    update = Update.de_json(payload, app_obj.bot)
    await app_obj.update_queue.put(update)
    return {"ok": True}
