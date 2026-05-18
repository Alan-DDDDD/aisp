"""Gap Detector — Phase A 對外入口（PLAN §22.4）。

流程：
  1. Planner：query → steps
  2. 對每個 requires_tool=true 的 step：
     a) Retrieval：找 top-K 候選 + max_similarity
     b) Similarity shortcut：> high 直接 USE / < low 直接 GAP / 中間進 judge
  3. 灰色區的 step batched 給 Judge LLM 一次判決
  4. Judge confidence 仍在灰色區 → 透過 HumanReviewInterface 詢問
  5. 每個 step 寫一筆 tool_decisions_audit
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import ToolDecisionAudit
from app.providers.base import LLMProvider
from app.synthesis.judge import Judge
from app.synthesis.planner import Planner
from app.synthesis.review import AutoDecideReview, HumanReviewInterface
from app.synthesis.schemas import (
    DecisionRoute,
    DecisionType,
    GapDetectionResult,
    JudgeStepDecision,
    PlannerStep,
    StepDecision,
    ToolCandidate,
    ToolSpec,
)
from app.synthesis.tool_retriever import ToolRetriever
from app.synthesis.tool_retriever import get_default as get_default_retriever

log = logging.getLogger(__name__)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


class GapDetector:
    """Phase A 主流程；可被注入 retriever / review impl（測試友善）。"""

    def __init__(
        self,
        provider: LLMProvider,
        retriever: ToolRetriever | None = None,
        review: HumanReviewInterface | None = None,
        planner: Planner | None = None,
        judge: Judge | None = None,
    ) -> None:
        self.provider = provider
        self.retriever = retriever or get_default_retriever()
        self.review = review or AutoDecideReview()
        self.planner = planner or Planner(provider=provider)
        self.judge = judge or Judge(provider=provider)

    async def detect(
        self,
        query: str,
        workspace_id: str = "default",
        *,
        session: AsyncSession | None = None,
    ) -> GapDetectionResult:
        query_id = _new_id("q")
        plan = await self.planner.plan(query)

        # Step 1：對每個 step 跑 retrieval + similarity shortcut
        gray_zone: list[tuple[PlannerStep, list[ToolCandidate]]] = []
        partial: dict[str, StepDecision] = {}

        for step in plan.steps:
            if not step.requires_tool:
                partial[step.id] = StepDecision(
                    step=step,
                    decision=DecisionType.USE,  # 「USE」代表「不用工具直接做」(by agent)
                    tool_id=None,
                    confidence=1.0,
                    candidates=[],
                    max_similarity=0.0,
                    route=DecisionRoute.NO_TOOL_NEEDED,
                    reasoning="planner 標記不需要工具",
                )
                continue

            candidates = self.retriever.retrieve(
                step.description,
                top_k=settings.gap_retrieval_top_k,
                workspace_id=workspace_id,
            )
            max_sim = candidates[0].similarity if candidates else 0.0

            if candidates and max_sim >= settings.gap_sim_high:
                top = candidates[0]
                partial[step.id] = StepDecision(
                    step=step,
                    decision=DecisionType.USE,
                    tool_id=top.tool_id,
                    confidence=max_sim,
                    candidates=candidates,
                    max_similarity=max_sim,
                    route=DecisionRoute.SHORTCUT_HIGH,
                    reasoning=f"retrieval max_sim={max_sim:.2f} >= {settings.gap_sim_high}",
                )
            elif max_sim <= settings.gap_sim_low:
                partial[step.id] = StepDecision(
                    step=step,
                    decision=DecisionType.GAP,
                    gap_spec=_default_gap_spec(step),
                    confidence=1.0 - max_sim,
                    candidates=candidates,
                    max_similarity=max_sim,
                    route=DecisionRoute.SHORTCUT_LOW,
                    reasoning=f"retrieval max_sim={max_sim:.2f} <= {settings.gap_sim_low}",
                )
            else:
                gray_zone.append((step, candidates))

        # Step 2：灰色 step 一次給 judge
        judge_decisions: dict[str, JudgeStepDecision] = {}
        if gray_zone:
            judge_decisions = await self.judge.judge(gray_zone)

        # Step 3：judge 仍灰的問人類
        for step, candidates in gray_zone:
            jd = judge_decisions.get(step.id)
            route = DecisionRoute.JUDGE
            if jd is not None and not _confidence_clear(jd.confidence):
                # 中間信心 → 人類介入
                jd = await self.review.ask_about_step(query, step, candidates, jd)
                route = DecisionRoute.HUMAN

            if jd is None:
                # 理論上 judge.judge() 已保證每 step 都有，這裡是防呆
                jd = await self.review.ask_about_step(query, step, candidates, None)
                route = DecisionRoute.HUMAN

            partial[step.id] = StepDecision(
                step=step,
                decision=jd.decision,
                tool_id=jd.tool_id,
                compose_chain=jd.compose_chain,
                gap_spec=jd.gap_spec or (
                    _default_gap_spec(step) if jd.decision is DecisionType.GAP else None
                ),
                confidence=jd.confidence,
                candidates=candidates,
                max_similarity=candidates[0].similarity if candidates else 0.0,
                route=route,
                reasoning=jd.reasoning,
                model_used=self.judge.model,
            )

        # Step 4：照原本 plan 順序組裝結果
        result = GapDetectionResult(
            query_id=query_id,
            query=query,
            workspace_id=workspace_id,
            steps=[partial[s.id] for s in plan.steps],
        )

        # Step 5：持久化 audit
        if session is not None:
            await _persist_audit(session, result)

        return result


def _confidence_clear(c: float) -> bool:
    return c >= settings.gap_conf_high or c <= settings.gap_conf_low


def _default_gap_spec(step: PlannerStep) -> ToolSpec:
    """Shortcut_low / 防呆時的占位 spec；M4 Code Agent 會做 spec 補完。"""
    return ToolSpec(
        name=f"auto_gap_{step.id}",
        description=step.description,
        when_to_use=step.description,
    )


async def _persist_audit(session: AsyncSession, result: GapDetectionResult) -> None:
    """把每個 step 的決策寫一筆 tool_decisions_audit。"""
    now = datetime.now(UTC)
    for sd in result.steps:
        row = ToolDecisionAudit(
            id=_new_id("dec"),
            query_id=result.query_id,
            step_id=sd.step.id,
            step_description=sd.step.description,
            workspace_id=result.workspace_id,
            decision=sd.decision.value,
            tool_id=sd.tool_id,
            compose_chain=sd.compose_chain,
            gap_spec=sd.gap_spec.model_dump() if sd.gap_spec else None,
            confidence=sd.confidence,
            candidates=[c.model_dump() for c in sd.candidates],
            max_similarity=sd.max_similarity,
            reasoning=sd.reasoning,
            route=sd.route.value,
            model_used=sd.model_used,
            created_at=now,
        )
        session.add(row)
    await session.commit()


# ── 公開的便利入口 ─────────────────────────────────────────────────


async def detect_gaps(
    query: str,
    provider: LLMProvider,
    workspace_id: str = "default",
    *,
    retriever: ToolRetriever | None = None,
    review: HumanReviewInterface | None = None,
    session: AsyncSession | None = None,
) -> GapDetectionResult:
    """單次 query 的 Phase A 入口。"""
    detector = GapDetector(provider=provider, retriever=retriever, review=review)
    return await detector.detect(query, workspace_id=workspace_id, session=session)
