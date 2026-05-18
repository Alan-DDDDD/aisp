"""Sender — 抽象 Telegram 寄送介面。

設計理由：notifier 業務碼只依賴這個介面，不直接拉 python-telegram-bot。
這樣：
  - 測試可用 FakeSender 驗證訊息內容與按鈕結構
  - 沒裝 python-telegram-bot 的 dev 環境也能 import notifier
  - 未來換 Slack / 自架 web dashboard 只需新增 Sender 實作
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class InlineButton:
    """Inline keyboard 單一按鈕。callback_data 必須是純 ASCII 且 <= 64 bytes。"""

    text: str
    callback_data: str


@dataclass
class SentMessage:
    """寄送後拿到的識別資訊。message_id 用來日後 edit / reply / delete。"""

    chat_id: str
    message_id: int


class Sender(ABC):
    @abstractmethod
    async def send(
        self,
        chat_id: str,
        text: str,
        *,
        buttons: list[list[InlineButton]] | None = None,
        parse_mode: str | None = "HTML",
    ) -> SentMessage:
        raise NotImplementedError

    @abstractmethod
    async def edit(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "HTML",
    ) -> None:
        raise NotImplementedError


class FakeSender(Sender):
    """測試與離線 dev 用。把每次呼叫存進 list 以便驗證。"""

    name = "fake"

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.edits: list[dict] = []
        self._next_id = 1

    async def send(
        self,
        chat_id: str,
        text: str,
        *,
        buttons: list[list[InlineButton]] | None = None,
        parse_mode: str | None = "HTML",
    ) -> SentMessage:
        msg_id = self._next_id
        self._next_id += 1
        self.sent.append(
            {
                "chat_id": chat_id,
                "text": text,
                "buttons": buttons or [],
                "parse_mode": parse_mode,
                "message_id": msg_id,
            }
        )
        log.debug("FakeSender.send chat_id=%s len=%d msg_id=%d", chat_id, len(text), msg_id)
        return SentMessage(chat_id=chat_id, message_id=msg_id)

    async def edit(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "HTML",
    ) -> None:
        self.edits.append(
            {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
        )


@dataclass
class PtbSenderConfig:
    """PtbSender 啟動參數。"""

    bot_token: str
    default_chat_id: str = ""
    parse_mode: str = "HTML"
    sources: list[str] = field(default_factory=list)  # 留作未來分流多 bot


class PtbSender(Sender):
    """python-telegram-bot Application 上的 Sender 實作。

    lazy import：缺套件時這個檔案仍能被 import（只是 instantiate 會 fail）。
    """

    name = "ptb"

    def __init__(self, config: PtbSenderConfig) -> None:
        self.config = config
        self._bot = None  # type: ignore[var-annotated]

    def _get_bot(self):
        if self._bot is None:
            try:
                from telegram import Bot  # type: ignore
            except ImportError as e:
                raise RuntimeError(
                    "python-telegram-bot 未安裝。請執行：pip install 'aisp-backend[telegram]'"
                ) from e
            from app.telegram._ssl import ensure_truststore

            ensure_truststore()
            self._bot = Bot(token=self.config.bot_token)
        return self._bot

    async def send(
        self,
        chat_id: str,
        text: str,
        *,
        buttons: list[list[InlineButton]] | None = None,
        parse_mode: str | None = "HTML",
    ) -> SentMessage:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup  # type: ignore

        markup = None
        if buttons:
            markup = InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton(text=b.text, callback_data=b.callback_data) for b in row]
                    for row in buttons
                ]
            )
        bot = self._get_bot()
        msg = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup,
            parse_mode=parse_mode,
        )
        return SentMessage(chat_id=str(msg.chat_id), message_id=msg.message_id)

    async def edit(
        self,
        chat_id: str,
        message_id: int,
        text: str,
        *,
        parse_mode: str | None = "HTML",
    ) -> None:
        bot = self._get_bot()
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=parse_mode,
        )
