"""TA2 — ToolAgent 單元測試。

涵蓋路徑：
  - 無 USE 也無 GAP（全 no_tool_needed）→ skipped_reason=no_tool_needed
  - 只有 GAP → skipped_reason=gap_detected + gap_specs 帶值（給 TA3 用）
  - USE 但 registry 沒這 tool → tool_missing_from_registry
  - happy path：USE → arg gen → call → tool_result 含預期值
  - arg gen 回 _error → skipped_reason=arg_gen_missing
  - input validation 失敗 → skipped_reason=input_validation
  - tool.call 拋例外 → error 欄位帶錯誤訊息
  - arg gen 回不可 parse → arg_gen_unparseable

不直接測 gap_detector cascading（它有自己 18 個測試）— 這裡注入 FakeGapDetector
直接拿到 canned GapDetectionResult。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agents.tool_agent import ToolAgent
from app.schemas.agent import AgentContext, ToolAgentInput
from app.synthesis.schemas import (
    DecisionRoute,
    DecisionType,
    GapDetectionResult,
    PlannerStep,
    StepDecision,
    ToolCandidate,
    ToolSpec,
)
from app.tools import registry as tool_registry
from app.tools.base import BaseTool, SideEffect
from tests._fakes import ScriptedProvider


# ── 範例 tool（test scope）──────────────────────────────────────────


class _CelsiusInput(BaseModel):
    celsius: float


class _CelsiusOutput(BaseModel):
    fahrenheit: float


class _CelsiusTool(BaseTool):
    id = "celsius_to_fahrenheit"
    description = "把攝氏溫度轉成華氏溫度"
    when_to_use = "使用者給攝氏度數要轉華氏"
    input_schema = _CelsiusInput
    output_schema = _CelsiusOutput
    side_effect = SideEffect.READ_ONLY

    async def call(self, ctx, payload: _CelsiusInput) -> _CelsiusOutput:
        return _CelsiusOutput(fahrenheit=payload.celsius * 9 / 5 + 32)


class _BoomTool(BaseTool):
    id = "always_boom"
    description = "故意爆炸的工具，用來測 call 失敗路徑"
    input_schema = _CelsiusInput
    output_schema = _CelsiusOutput
    side_effect = SideEffect.READ_ONLY

    async def call(self, ctx, payload: _CelsiusInput) -> _CelsiusOutput:
        raise RuntimeError("simulated tool failure")


# ── FakeGapDetector ─────────────────────────────────────────────────


class FakeGapDetector:
    """duck-typed gap_detector：直接吐 canned GapDetectionResult。"""

    def __init__(self, result: GapDetectionResult) -> None:
        self.result = result

    async def detect(self, query: str, workspace_id: str = "default", *, session=None):
        return self.result


def _step_use(step_id: str, desc: str, tool_id: str, sim: float = 0.78) -> StepDecision:
    return StepDecision(
        step=PlannerStep(id=step_id, description=desc, requires_tool=True),
        decision=DecisionType.USE,
        tool_id=tool_id,
        confidence=sim,
        candidates=[ToolCandidate(tool_id=tool_id, similarity=sim, description="d")],
        max_similarity=sim,
        route=DecisionRoute.JUDGE,
        reasoning="test",
    )


def _step_gap(step_id: str, desc: str, gap_name: str) -> StepDecision:
    spec = ToolSpec(name=gap_name, description=desc, when_to_use=desc)
    return StepDecision(
        step=PlannerStep(id=step_id, description=desc, requires_tool=True),
        decision=DecisionType.GAP,
        gap_spec=spec,
        confidence=0.9,
        candidates=[],
        max_similarity=0.0,
        route=DecisionRoute.SHORTCUT_LOW,
        reasoning="no tool",
    )


def _step_skip(step_id: str, desc: str) -> StepDecision:
    return StepDecision(
        step=PlannerStep(id=step_id, description=desc, requires_tool=False),
        decision=DecisionType.USE,
        tool_id=None,
        confidence=1.0,
        candidates=[],
        max_similarity=0.0,
        route=DecisionRoute.NO_TOOL_NEEDED,
        reasoning="not needed",
    )


def _result(steps: list[StepDecision]) -> GapDetectionResult:
    return GapDetectionResult(
        query_id="q-test", query="test", workspace_id="cs", steps=steps
    )


@pytest.fixture(autouse=True)
def _isolate_registry():
    tool_registry.clear()
    yield
    tool_registry.clear()


def _ctx() -> AgentContext:
    return AgentContext(workspace_id="cs", room_id="r", trace_id="t")


def _agent(result: GapDetectionResult, llm_responses: list[str] | None = None):
    return ToolAgent(
        provider=ScriptedProvider(llm_responses or []),
        gap_detector=FakeGapDetector(result),
    )


# ── tests ───────────────────────────────────────────────────────────


async def test_all_no_tool_needed_skips():
    agent = _agent(_result([_step_skip("s1", "聊天")]))

    out = await agent.run(_ctx(), ToolAgentInput(message="嗨"))

    assert out.tool_called is None
    assert out.skipped_reason == "no_tool_needed"
    assert out.gap_specs == []


async def test_gap_only_returns_gap_specs():
    agent = _agent(_result([_step_gap("s1", "計算複雜統計", "advanced_stats")]))

    out = await agent.run(_ctx(), ToolAgentInput(message="幫我算 90 天平均餘額"))

    assert out.tool_called is None
    assert out.skipped_reason == "gap_detected"
    assert len(out.gap_specs) == 1
    assert out.gap_specs[0]["name"] == "advanced_stats"


async def test_use_but_tool_missing_from_registry():
    agent = _agent(_result([_step_use("s1", "x", "ghost_tool")]))

    out = await agent.run(_ctx(), ToolAgentInput(message="x"))

    assert out.tool_called is None
    assert out.skipped_reason == "tool_missing_from_registry"


async def test_happy_path_calls_tool():
    tool_registry.register(_CelsiusTool())
    agent = _agent(
        _result([_step_use("s1", "轉換溫度", "celsius_to_fahrenheit")]),
        llm_responses=['{"celsius": 32}'],
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="攝氏 32 度是華氏幾度"))

    assert out.tool_called == "celsius_to_fahrenheit"
    assert out.tool_result == {"fahrenheit": 32 * 9 / 5 + 32}
    assert out.skipped_reason is None
    assert out.error is None


async def test_arg_gen_missing_required():
    tool_registry.register(_CelsiusTool())
    agent = _agent(
        _result([_step_use("s1", "轉換溫度", "celsius_to_fahrenheit")]),
        llm_responses=['{"_error": "missing field: celsius"}'],
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="幫我轉換溫度"))

    assert out.tool_called is None
    assert out.skipped_reason.startswith("arg_gen_missing")


async def test_input_validation_fails():
    tool_registry.register(_CelsiusTool())
    agent = _agent(
        _result([_step_use("s1", "轉換溫度", "celsius_to_fahrenheit")]),
        llm_responses=['{"celsius": {"bad": "type"}}'],
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="轉換 abc 度"))

    assert out.tool_called is None
    assert out.skipped_reason.startswith("input_validation")


async def test_tool_call_failure_captured():
    tool_registry.register(_BoomTool())
    agent = _agent(
        _result([_step_use("s1", "炸一下", "always_boom")]),
        llm_responses=['{"celsius": 10}'],
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="炸一下"))

    assert out.tool_called == "always_boom"
    assert out.error is not None
    assert "simulated tool failure" in out.error
    assert out.tool_result is None


async def test_arg_gen_unparseable_response():
    tool_registry.register(_CelsiusTool())
    agent = _agent(
        _result([_step_use("s1", "x", "celsius_to_fahrenheit")]),
        llm_responses=["totally not json 完全壞掉"],
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="x"))

    assert out.tool_called is None
    assert out.skipped_reason == "arg_gen_unparseable"


async def test_multi_step_picks_first_use_step():
    """planner 拆多 step 時，tool_agent 只挑第一個 USE step 呼叫一次。"""
    tool_registry.register(_CelsiusTool())
    agent = _agent(
        _result(
            [
                _step_skip("s1", "解析輸入"),  # no_tool_needed
                _step_use("s2", "做轉換", "celsius_to_fahrenheit"),
                _step_skip("s3", "回傳結果"),
            ]
        ),
        llm_responses=['{"celsius": 100}'],
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="攝氏 100 度轉華氏"))

    assert out.tool_called == "celsius_to_fahrenheit"
    assert out.tool_result == {"fahrenheit": 212.0}


async def test_use_takes_priority_over_gap():
    """USE 跟 GAP 同時存在時，USE 先做（gap_specs 不會出現）。"""
    tool_registry.register(_CelsiusTool())
    agent = _agent(
        _result(
            [
                _step_use("s1", "做轉換", "celsius_to_fahrenheit"),
                _step_gap("s2", "順便算個東西", "other_thing"),
            ]
        ),
        llm_responses=['{"celsius": 0}'],
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="把 0 度轉華氏並算另一件事"))

    assert out.tool_called == "celsius_to_fahrenheit"
    assert out.gap_specs == []
