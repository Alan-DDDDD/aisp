"""Telegram HITL 子套件 — PLAN §22.4.4 / §22.5.7。

公開介面：
  Sender          抽象介面，notifier 只跟它互動，方便測試替換
  PtbSender       python-telegram-bot 實作（lazy import）
  Notifier        高階 API：notify_gray_zone / notify_approval / notify_rescue
  PendingRequests 短期未決 future 倉儲
  TelegramReview  HumanReviewInterface 的 Telegram 實作
  callback_router 處理 inline keyboard callback_data

設計：notifier 與 bot lifecycle 解耦。Sender 介面允許測試注入 fake，
PROD 才 wire 真實 python-telegram-bot Application。
"""

from app.telegram.notifier import Notifier
from app.telegram.pending import PendingRequests
from app.telegram.sender import FakeSender, Sender

__all__ = [
    "FakeSender",
    "Notifier",
    "PendingRequests",
    "Sender",
]
