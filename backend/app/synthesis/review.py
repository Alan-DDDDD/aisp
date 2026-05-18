"""HumanReviewInterface — Phase 6 全系統的人類介入介面。

M2 階段：只實作 AutoDecideReview（無人類，按 confidence 自動決）。
M3 起會加 TelegramReview。所有上層流程（gap_detector / approval flow）
透過這個 interface 跟人類互動，避免散落各處的耦合。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from app.synthesis.schemas import (
    DecisionType,
    JudgeStepDecision,
    PlannerStep,
    ToolCandidate,
    ToolSpec,
)

log = logging.getLogger(__name__)


class HumanReviewInterface(ABC):
    """所有人類介入點的統一介面。

    method 命名規則：ask_about_* 表示「請人類做選擇」，會阻塞到拿到回應為止。
    """

    @abstractmethod
    async def ask_about_step(
        self,
        query: str,
        step: PlannerStep,
        candidates: list[ToolCandidate],
        judge_hint: JudgeStepDecision | None,
    ) -> JudgeStepDecision:
        """灰色信心區（PLAN §22.4.4）詢問人類該 USE 哪個還是 GAP。

        實作可以阻塞、可以非同步等候、可以 timeout fallback —— 由 impl 決定。
        """
        raise NotImplementedError


class AutoDecideReview(HumanReviewInterface):
    """M2 用：無人類介入版本。

    策略：信任 judge 的 hint；如果 judge 沒給就 fallback 到 retrieval top-1。
    這是「先讓系統能跑」的占位版，M3 會替換成 Telegram。
    """

    async def ask_about_step(
        self,
        query: str,
        step: PlannerStep,
        candidates: list[ToolCandidate],
        judge_hint: JudgeStepDecision | None,
    ) -> JudgeStepDecision:
        if judge_hint is not None:
            log.info(
                "AutoDecideReview: 採用 judge 既有決策 step=%s decision=%s confidence=%.2f",
                step.id,
                judge_hint.decision,
                judge_hint.confidence,
            )
            return judge_hint

        if candidates:
            top = candidates[0]
            return JudgeStepDecision(
                step_id=step.id,
                decision=DecisionType.USE,
                tool_id=top.tool_id,
                confidence=top.similarity,
                reasoning="AutoDecideReview: 無 judge hint，採用 retrieval top-1",
            )

        return JudgeStepDecision(
            step_id=step.id,
            decision=DecisionType.GAP,
            gap_spec=ToolSpec(
                name=f"auto_gap_{step.id}",
                description=step.description,
                when_to_use=step.description,
            ),
            confidence=0.0,
            reasoning="AutoDecideReview: 無候選工具且無 judge hint，保守判 GAP",
        )
