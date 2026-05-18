"""Phase 6 M3 — TelegramReview 與 callback handler 的端到端 fake 流程。"""

from __future__ import annotations

import asyncio

from app.synthesis.schemas import (
    DecisionType,
    JudgeStepDecision,
    PlannerStep,
    ToolCandidate,
)
from app.telegram.bot import FakeBot
from app.telegram.notifier import Notifier
from app.telegram.pending import PendingRequests
from app.telegram.review import TelegramReview


def _step() -> PlannerStep:
    return PlannerStep(id="s1", description="查訂單", requires_tool=True)


async def test_telegram_review_user_picks_tool():
    """完整路徑：ask → 推訊息 → user 按按鈕 → review 拿到結果。"""
    bot = FakeBot()
    pending = PendingRequests()
    notifier = Notifier(bot.sender(), default_chat_id="chat-1")
    review = TelegramReview(notifier=notifier, pending=pending, chat_id="chat-1", timeout_s=5)
    bot.register_gray_handler(review.on_gray_callback)

    candidates = [ToolCandidate(tool_id="kb_search", similarity=0.6, description="x")]

    async def _user_clicks():
        # 等 ask_about_step 把訊息送出
        await asyncio.sleep(0.05)
        # 取 sent 訊息的 callback_data，模擬使用者按下「USE kb_search」
        sender = bot.sender()
        sent = sender.sent[0]  # type: ignore[attr-defined]
        button = sent["buttons"][0][0]  # 第一行第一顆
        await bot.trigger_callback(button.callback_data, "chat-1", sent["message_id"])

    asyncio.create_task(_user_clicks())

    out = await review.ask_about_step(
        query="客戶 C-123 上個月買了什麼？",
        step=_step(),
        candidates=candidates,
        judge_hint=None,
    )
    assert out.decision is DecisionType.USE
    assert out.tool_id == "kb_search"


async def test_telegram_review_timeout_falls_back_to_hint():
    bot = FakeBot()
    pending = PendingRequests()
    notifier = Notifier(bot.sender(), default_chat_id="chat-1")
    review = TelegramReview(notifier=notifier, pending=pending, chat_id="chat-1", timeout_s=0.05)
    bot.register_gray_handler(review.on_gray_callback)

    hint = JudgeStepDecision(
        step_id="s1", decision=DecisionType.USE, tool_id="hint_tool", confidence=0.6
    )
    out = await review.ask_about_step(
        query="x",
        step=_step(),
        candidates=[ToolCandidate(tool_id="other", similarity=0.5, description="x")],
        judge_hint=hint,
    )
    # timeout 後採信 judge_hint
    assert out is hint


async def test_telegram_review_user_picks_gap():
    bot = FakeBot()
    pending = PendingRequests()
    notifier = Notifier(bot.sender(), default_chat_id="chat-1")
    review = TelegramReview(notifier=notifier, pending=pending, chat_id="chat-1", timeout_s=5)
    bot.register_gray_handler(review.on_gray_callback)

    async def _user_picks_gap():
        await asyncio.sleep(0.05)
        sender = bot.sender()
        sent = sender.sent[0]  # type: ignore[attr-defined]
        # 找「GAP」按鈕（最後一行）
        gap_btn = sent["buttons"][-1][0]
        await bot.trigger_callback(gap_btn.callback_data, "chat-1", sent["message_id"])

    asyncio.create_task(_user_picks_gap())

    out = await review.ask_about_step(
        query="x",
        step=_step(),
        candidates=[ToolCandidate(tool_id="kb_search", similarity=0.5, description="x")],
        judge_hint=None,
    )
    assert out.decision is DecisionType.GAP
    assert out.gap_spec is not None
