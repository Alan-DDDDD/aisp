"""Phase 6 — Process-wide singletons & FastAPI lifespan glue（PLAN §22 整合）。

這個 module 是 M7 的「接著點」：把 M2-M6 的零件兜起來放進 process，
讓 main.py 與 API endpoints 透過 Depends 取得同一份 instance。

設計重點：
- 單例 lazy create，沒設定 TG_BOT_TOKEN 時 bot 退到 FakeBot（不打網路）
- on_startup 接 SessionLocal-like factory，避免直接依賴 DB module（測試友善）
- 所有 getter 都對外開放，給 FastAPI Depends 用
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.synthesis.approval import ApprovalService
from app.synthesis.registry_loader import load_all_active
from app.synthesis.tool_retriever import ToolRetriever
from app.synthesis.tool_retriever import get_default as get_default_retriever
from app.telegram.bot import TelegramBot, build_default_bot
from app.telegram.notifier import Notifier
from app.telegram.pending import PendingRequests
from app.telegram.pending import get_default as get_default_pending
from app.telegram.review import TelegramReview

log = logging.getLogger(__name__)


# Session factory 型別：no-arg callable，回 async context manager → AsyncSession
SessionFactory = Callable[[], "_SessionCtx"]


class _SessionCtx:  # pragma: no cover — duck-type marker
    async def __aenter__(self) -> AsyncSession: ...
    async def __aexit__(self, *a): ...


# ── 單例 ─────────────────────────────────────────────────────────────


_bot: TelegramBot | None = None
_notifier: Notifier | None = None
_pending: PendingRequests | None = None
_approval: ApprovalService | None = None
_review: TelegramReview | None = None


def get_bot() -> TelegramBot:
    global _bot
    if _bot is None:
        _bot = build_default_bot()
    return _bot


def get_pending() -> PendingRequests:
    global _pending
    if _pending is None:
        _pending = get_default_pending()
    return _pending


def get_notifier() -> Notifier:
    global _notifier
    if _notifier is None:
        _notifier = Notifier(get_bot().sender(), default_chat_id=settings.tg_chat_id)
    return _notifier


def get_retriever() -> ToolRetriever:
    return get_default_retriever()


def get_approval_service() -> ApprovalService:
    global _approval
    if _approval is None:
        _approval = ApprovalService(
            notifier=get_notifier(),
            retriever=get_retriever(),
            default_chat_id=settings.tg_chat_id,
        )
    return _approval


def get_telegram_review() -> TelegramReview:
    global _review
    if _review is None:
        _review = TelegramReview(
            notifier=get_notifier(),
            pending=get_pending(),
            chat_id=settings.tg_chat_id,
        )
    return _review


def reset() -> None:
    """測試用 — 把所有 singleton 清掉，避免 test 互相污染。"""
    global _bot, _notifier, _pending, _approval, _review
    _bot = None
    _notifier = None
    _pending = None
    _approval = None
    _review = None


# ── Lifespan helpers ────────────────────────────────────────────────


async def on_startup(session_factory: SessionFactory) -> None:
    """app 啟動時呼叫一次。順序很重要：

    1. 載入 generated tools 進 registry（讓 retriever rebuild 時看得到它們）
    2. 註冊 bot 的 callback handlers（gray review + approval）
    3. 啟動 bot 收訊息（只有設了 TG_BOT_TOKEN 才真的連線）
    """
    # 1. Generated tools
    try:
        async with session_factory() as session:
            n = await load_all_active(session)
        log.info("on_startup: loaded %d generated tools", n)
    except Exception as e:  # noqa: BLE001
        log.exception("on_startup: load_all_active 失敗：%s", e)

    # 1b. 把 builtin + generated tool 都 embed 進 retriever index。
    # 沒做這步的話：load_all_active 只用 add_tool 加 generated，builtin 缺席 →
    # 任何 query 的 candidates 都是空的（之前 demo 撞到的 bug）。
    try:
        get_retriever().build()
        log.info("on_startup: retriever index 重建完成")
    except Exception as e:  # noqa: BLE001
        log.warning("on_startup: retriever.build() 失敗（不擋啟動）：%s", e)

    # 2 + 3. Telegram bot
    if not settings.tg_bot_token:
        log.info("on_startup: TG_BOT_TOKEN 空，Telegram HITL 停用（仍提供 FakeBot 供測試）")
        return

    bot = get_bot()
    review = get_telegram_review()
    approval = get_approval_service()
    bot.register_gray_handler(review.on_gray_callback)
    bot.register_approval_handler(approval.make_callback_handler(session_factory))
    try:
        await bot.start()
        log.info("on_startup: Telegram bot started (mode=%s)", settings.tg_mode)
    except Exception as e:  # noqa: BLE001
        log.exception("on_startup: Telegram bot 啟動失敗：%s", e)


async def on_shutdown() -> None:
    """app 關閉時呼叫一次。"""
    if _bot is None:
        return
    with contextlib.suppress(Exception):
        await _bot.stop()
        log.info("on_shutdown: Telegram bot stopped")
