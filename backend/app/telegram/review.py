"""TelegramReview — HumanReviewInterface 的 Telegram 實作（PLAN §22.4.4）。

流程：
  1. ask_about_step()：建 PendingEntry → 透過 Notifier 寄問題 → await future
  2. 使用者按按鈕 → bot.py 解析 callback → 呼叫 on_gray_callback()
  3. on_gray_callback() 完成 future → ask_about_step() 拿到結果並回傳

timeout 時 fallback 回 judge_hint（避免任務永遠 pending）。
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.synthesis.review import HumanReviewInterface
from app.synthesis.schemas import (
    DecisionType,
    JudgeStepDecision,
    PlannerStep,
    ToolCandidate,
    ToolSpec,
)
from app.telegram.callback_router import GrayCallback
from app.telegram.notifier import Notifier
from app.telegram.pending import PendingRequests

log = logging.getLogger(__name__)


class TelegramReview(HumanReviewInterface):
    """灰色信心區把 step 推給使用者選擇。

    使用方式：
        review = TelegramReview(notifier=..., pending=..., chat_id="...")
        # bot.py 啟動時：
        bot.register_gray_handler(review.on_gray_callback)
    """

    def __init__(
        self,
        notifier: Notifier,
        pending: PendingRequests,
        chat_id: str | None = None,
        timeout_s: int | None = None,
    ) -> None:
        self.notifier = notifier
        self.pending = pending
        self.chat_id = chat_id or settings.tg_chat_id
        self.timeout_s = timeout_s if timeout_s is not None else settings.tg_review_timeout_s

    async def ask_about_step(
        self,
        query: str,
        step: PlannerStep,
        candidates: list[ToolCandidate],
        judge_hint: JudgeStepDecision | None,
    ) -> JudgeStepDecision:
        # 建未決 entry
        entry = await self.pending.create(
            purpose=f"gray_zone:{step.id}",
            step_id=step.id,
            judge_hint=judge_hint.model_dump() if judge_hint else None,
        )

        # 送 Telegram
        try:
            await self.notifier.notify_gray_zone(
                interaction_id=entry.interaction_id,
                query=query,
                step=step,
                candidates=candidates,
                chat_id=self.chat_id,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("TelegramReview 發送失敗，fallback hint: %s", e)
            return _fallback(step, candidates, judge_hint)

        # 等使用者回應
        try:
            result = await self.pending.wait(entry.interaction_id, timeout=self.timeout_s)
        except TimeoutError:
            log.info("TelegramReview timeout（%ds），fallback hint", self.timeout_s)
            return _fallback(step, candidates, judge_hint)
        except asyncio.CancelledError:
            raise

        return _decode_user_decision(result, step, judge_hint)

    async def on_gray_callback(
        self,
        callback: GrayCallback,
        chat_id: str,
        message_id: int,
    ) -> None:
        """bot.py 的 GrayHandler 入口。"""
        result: dict[str, object]
        if callback.kind == "use":
            result = {"decision": "USE", "tool_id": callback.tool_id}
        else:
            result = {"decision": "GAP"}

        ok = await self.pending.complete(callback.interaction_id, result)
        if not ok:
            log.warning(
                "TelegramReview.on_gray_callback: interaction 找不到或已過期 id=%s",
                callback.interaction_id,
            )

        # 不阻塞使用者：嘗試把訊息加註已處理（失敗就算了）
        try:
            await self.notifier.sender.edit(
                chat_id=chat_id,
                message_id=message_id,
                text="✅ 已記錄你的選擇，回任務繼續執行。",
                parse_mode=None,
            )
        except Exception as e:  # noqa: BLE001
            log.debug("edit message 失敗（可忽略）：%s", e)


def _decode_user_decision(
    payload: dict,
    step: PlannerStep,
    judge_hint: JudgeStepDecision | None,
) -> JudgeStepDecision:
    decision = payload.get("decision")
    if decision == "USE":
        tool_id = payload.get("tool_id")
        return JudgeStepDecision(
            step_id=step.id,
            decision=DecisionType.USE,
            tool_id=str(tool_id) if tool_id else None,
            confidence=1.0,
            reasoning="人類選擇此工具",
        )
    if decision == "GAP":
        return JudgeStepDecision(
            step_id=step.id,
            decision=DecisionType.GAP,
            gap_spec=ToolSpec(
                name=f"human_gap_{step.id}",
                description=step.description,
                when_to_use=step.description,
            ),
            confidence=1.0,
            reasoning="人類判定需要做新工具",
        )
    # 不認得的 payload → 回 judge_hint
    return judge_hint or JudgeStepDecision(
        step_id=step.id,
        decision=DecisionType.GAP,
        confidence=0.0,
        reasoning="Telegram callback payload 未知，fallback",
    )


def _fallback(
    step: PlannerStep,
    candidates: list[ToolCandidate],
    judge_hint: JudgeStepDecision | None,
) -> JudgeStepDecision:
    """timeout / 寄送失敗時的 fallback；優先採信 judge_hint，否則 retrieval top-1。"""
    if judge_hint is not None:
        return judge_hint
    if candidates:
        top = candidates[0]
        return JudgeStepDecision(
            step_id=step.id,
            decision=DecisionType.USE,
            tool_id=top.tool_id,
            confidence=top.similarity,
            reasoning="TelegramReview 無法取得人類回應，採用 retrieval top-1",
        )
    return JudgeStepDecision(
        step_id=step.id,
        decision=DecisionType.GAP,
        confidence=0.0,
        reasoning="TelegramReview 無人類回應且無候選工具",
    )
