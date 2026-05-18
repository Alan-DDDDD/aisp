"""TelegramBot — lifecycle scaffolding（PLAN §22.4.4 / §22.5.7）。

設計：
- python-telegram-bot 是 optional dep；缺套件時這個檔仍可 import，
  TelegramBot.start() 才會 raise 引導使用者安裝。
- 兩種模式：polling（dev，無公網 URL）/ webhook（PROD）。
- 收到 callback_query 時，呼叫 router.parse_callback() 再分派給對應 handler。
- handler 為 callable（async def fn(callback, chat_id, message_id) -> None），
  由 ApprovalService / TelegramReview 註冊。

骨架定義在 `_HandlerRegistry`，實際 PTB Application 啟動實作放在 `_PtbBot`。
測試使用 `FakeBot` 不啟動真實 Telegram。
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from app.config import settings
from app.telegram.callback_router import (
    ApprovalCallback,
    GrayCallback,
    parse_callback,
)

if TYPE_CHECKING:
    from app.telegram.sender import Sender

log = logging.getLogger(__name__)


# Handler signature：拿到 parsed callback 與 telegram context
GrayHandler = Callable[[GrayCallback, str, int], Awaitable[None]]
ApprovalHandler = Callable[[ApprovalCallback, str, int], Awaitable[None]]


class TelegramBot(ABC):
    """Bot lifecycle 介面。`start()` 開始接收訊息；`stop()` 收尾。"""

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def register_gray_handler(self, handler: GrayHandler) -> None: ...

    @abstractmethod
    def register_approval_handler(self, handler: ApprovalHandler) -> None: ...

    @abstractmethod
    def sender(self) -> Sender:
        """取得對應的 Sender 實作，給 Notifier 用。"""


class FakeBot(TelegramBot):
    """測試用 bot：不發任何網路請求，可直接觸發 callback。"""

    def __init__(self) -> None:
        from app.telegram.sender import FakeSender

        self._sender = FakeSender()
        self._gray: GrayHandler | None = None
        self._approval: ApprovalHandler | None = None
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def register_gray_handler(self, handler: GrayHandler) -> None:
        self._gray = handler

    def register_approval_handler(self, handler: ApprovalHandler) -> None:
        self._approval = handler

    def sender(self) -> Sender:
        return self._sender

    async def trigger_callback(self, callback_data: str, chat_id: str, message_id: int) -> None:
        """測試用：模擬使用者按按鈕。"""
        parsed = parse_callback(callback_data)
        if parsed is None:
            log.warning("FakeBot.trigger_callback: unparseable data=%r", callback_data)
            return
        if isinstance(parsed, GrayCallback) and self._gray:
            await self._gray(parsed, chat_id, message_id)
        elif isinstance(parsed, ApprovalCallback) and self._approval:
            await self._approval(parsed, chat_id, message_id)


class PtbBot(TelegramBot):
    """python-telegram-bot 實作。lazy import，缺套件時 start() 才丟錯。

    M3 為骨架：
      - polling 模式由 PTB Application 自管，start() 啟一個 task
      - webhook 模式留 placeholder：由 FastAPI route 接 update 後丟給
        Application.update_queue（細節在 M7 整合時補）
    """

    def __init__(self) -> None:
        self._app = None  # type: ignore[var-annotated]
        self._sender = None  # type: ignore[var-annotated]
        self._gray: GrayHandler | None = None
        self._approval: ApprovalHandler | None = None
        self._polling_task: asyncio.Task[None] | None = None

    def _ensure_app(self):
        if self._app is None:
            try:
                from telegram.ext import (  # type: ignore
                    Application,
                    CallbackQueryHandler,
                )
            except ImportError as e:
                raise RuntimeError(
                    "python-telegram-bot 未安裝。請執行 pip install 'aisp-backend[telegram]'"
                ) from e
            if not settings.tg_bot_token:
                raise RuntimeError("TG_BOT_TOKEN 未設定")
            # 企業網路 self-signed CA 修補（PLAN §22.5 / GroqProvider 同模式）
            from app.telegram._ssl import ensure_truststore

            ensure_truststore()
            self._app = Application.builder().token(settings.tg_bot_token).build()
            self._app.add_handler(CallbackQueryHandler(self._on_callback))
        return self._app

    async def start(self) -> None:
        app = self._ensure_app()
        if settings.tg_mode == "polling":
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
            log.info("PtbBot started (polling)")
        elif settings.tg_mode == "webhook":
            await app.initialize()
            await app.start()
            log.info("PtbBot started (webhook); route 由 FastAPI 提供")
        else:
            raise ValueError(f"unknown TG_MODE: {settings.tg_mode}")

    async def stop(self) -> None:
        if self._app is None:
            return
        if settings.tg_mode == "polling":
            try:
                await self._app.updater.stop()
            except Exception as e:  # noqa: BLE001
                log.warning("PtbBot updater.stop: %s", e)
        try:
            await self._app.stop()
            await self._app.shutdown()
        except Exception as e:  # noqa: BLE001
            log.warning("PtbBot shutdown: %s", e)

    def register_gray_handler(self, handler: GrayHandler) -> None:
        self._gray = handler

    def register_approval_handler(self, handler: ApprovalHandler) -> None:
        self._approval = handler

    def sender(self) -> Sender:
        if self._sender is None:
            from app.telegram.sender import PtbSender, PtbSenderConfig

            self._sender = PtbSender(
                PtbSenderConfig(
                    bot_token=settings.tg_bot_token,
                    default_chat_id=settings.tg_chat_id,
                )
            )
        return self._sender

    async def _on_callback(self, update, ctx):  # noqa: ARG002 — PTB signature
        """PTB CallbackQueryHandler 進入點。"""
        query = update.callback_query
        if query is None:
            return
        await query.answer()  # 通知 Telegram 我們收到了

        parsed = parse_callback(query.data or "")
        chat_id = str(query.message.chat_id) if query.message else ""
        message_id = query.message.message_id if query.message else 0

        if isinstance(parsed, GrayCallback) and self._gray:
            await self._gray(parsed, chat_id, message_id)
        elif isinstance(parsed, ApprovalCallback) and self._approval:
            await self._approval(parsed, chat_id, message_id)
        else:
            log.warning("PtbBot._on_callback: 無法分派 data=%r", query.data)


def build_default_bot() -> TelegramBot:
    """依設定選 PtbBot / FakeBot。TG_BOT_TOKEN 空字串 → FakeBot（停用）。"""
    if not settings.tg_bot_token:
        return FakeBot()
    return PtbBot()
