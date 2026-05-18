"""Phase 6 M2 — Judge LLM 解析與 fallback。"""

from __future__ import annotations

from app.synthesis.judge import Judge
from app.synthesis.schemas import DecisionType, PlannerStep, ToolCandidate
from tests._fakes import ScriptedProvider


def _step(id: str, desc: str = "x") -> PlannerStep:
    return PlannerStep(id=id, description=desc, requires_tool=True)


def _cand(tid: str, sim: float = 0.6) -> ToolCandidate:
    return ToolCandidate(tool_id=tid, similarity=sim, description=f"desc of {tid}")


async def test_judge_parses_batched_decisions():
    provider = ScriptedProvider([
        '{"decisions": ['
        '{"step_id": "s1", "decision": "USE", "tool_id": "kb_search", "confidence": 0.9},'
        '{"step_id": "s2", "decision": "GAP", "gap_spec": '
        '{"name": "get_order_by_id", "description": "...", "when_to_use": "..."},'
        '"confidence": 0.2}'
        ']}',
    ])
    judge = Judge(provider=provider)
    items = [
        (_step("s1"), [_cand("kb_search", 0.7)]),
        (_step("s2"), []),
    ]
    decisions = await judge.judge(items)

    assert decisions["s1"].decision is DecisionType.USE
    assert decisions["s1"].tool_id == "kb_search"
    assert decisions["s2"].decision is DecisionType.GAP
    assert decisions["s2"].gap_spec is not None
    assert decisions["s2"].gap_spec.name == "get_order_by_id"


async def test_judge_fills_missing_steps_with_gap():
    """LLM 沒對某個 step 給出決策時，保守判 GAP，避免靜默忽略。"""
    provider = ScriptedProvider([
        '{"decisions": [{"step_id": "s1", "decision": "USE", "tool_id": "x", "confidence": 0.8}]}',
    ])
    judge = Judge(provider=provider)
    items = [
        (_step("s1"), [_cand("x")]),
        (_step("s2"), [_cand("y")]),
    ]
    decisions = await judge.judge(items)
    assert decisions["s1"].decision is DecisionType.USE
    assert decisions["s2"].decision is DecisionType.GAP


async def test_judge_fallback_on_parse_error():
    """LLM 整批回 garbage 時，採用 retrieval top-1 作為 USE，至少讓 pipeline 走得下去。"""
    provider = ScriptedProvider(["definitely not JSON"])
    judge = Judge(provider=provider)
    items = [(_step("s1"), [_cand("top_one", 0.71)])]
    decisions = await judge.judge(items)
    assert decisions["s1"].decision is DecisionType.USE
    assert decisions["s1"].tool_id == "top_one"
    # fallback confidence 應該對得上 retrieval similarity
    assert abs(decisions["s1"].confidence - 0.71) < 1e-6


async def test_judge_empty_input_returns_empty_dict():
    judge = Judge(provider=ScriptedProvider([]))
    assert await judge.judge([]) == {}
