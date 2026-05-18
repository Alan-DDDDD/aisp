"""Phase 6 M2 — AutoDecideReview 在無人類介入時的策略。"""

from __future__ import annotations

from app.synthesis.review import AutoDecideReview
from app.synthesis.schemas import (
    DecisionType,
    JudgeStepDecision,
    PlannerStep,
    ToolCandidate,
)


def _step() -> PlannerStep:
    return PlannerStep(id="s1", description="x", requires_tool=True)


async def test_auto_decide_uses_judge_hint_when_present():
    review = AutoDecideReview()
    hint = JudgeStepDecision(
        step_id="s1", decision=DecisionType.USE, tool_id="kb_search", confidence=0.7
    )
    out = await review.ask_about_step(
        query="q", step=_step(), candidates=[], judge_hint=hint
    )
    assert out is hint


async def test_auto_decide_falls_back_to_top_candidate():
    review = AutoDecideReview()
    cand = ToolCandidate(tool_id="kb_search", similarity=0.6, description="x")
    out = await review.ask_about_step(
        query="q", step=_step(), candidates=[cand], judge_hint=None
    )
    assert out.decision is DecisionType.USE
    assert out.tool_id == "kb_search"


async def test_auto_decide_returns_gap_when_no_candidates():
    review = AutoDecideReview()
    out = await review.ask_about_step(
        query="q", step=_step(), candidates=[], judge_hint=None
    )
    assert out.decision is DecisionType.GAP
    assert out.gap_spec is not None
