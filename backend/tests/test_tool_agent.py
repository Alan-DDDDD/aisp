"""TA3 — ToolAgent 單元測試（含合成路徑）。

涵蓋路徑：
  TA2：
  - 無 USE 也無 GAP（全 no_tool_needed）→ skipped_reason=no_tool_needed
  - 只有 GAP 但沒注入合成能力 → gap_detected + gap_specs 帶值
  - USE 但 registry 沒這 tool → tool_missing_from_registry
  - happy path：USE → arg gen → call → tool_result 含預期值
  - arg gen 回 _error → skipped_reason=arg_gen_missing
  - input validation 失敗 → skipped_reason=input_validation
  - tool.call 拋例外 → error 欄位帶錯誤訊息
  - arg gen 回不可 parse → arg_gen_unparseable
  - multi-step 拿第一個 USE / USE 優先 GAP

  TA3（嚴格 HITL，無 auto-approve）：
  - GAP + 可合成 + 成功 → submit → awaiting_approval（任何 side_effect 都一樣）
  - GAP + 可合成 + 失敗 → submit → synthesis_failed（task 進 AWAITING_HUMAN_RESCUE）

不直接測 gap_detector cascading（它有自己 18 個測試）— 這裡注入 FakeGapDetector
直接拿到 canned GapDetectionResult。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agents.tool_agent import ToolAgent
from app.schemas.agent import AgentContext, ToolAgentInput
from app.synthesis.orchestrator import SynthesisResult
from app.synthesis.schemas import (
    ConcreteExample,
    DecisionRoute,
    DecisionType,
    EnrichedToolSpec,
    FieldSpec,
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
    """duck-typed gap_detector：吐 canned 結果。

    可傳單一 result（每次 detect 都回同一個）或 list（每次依序消費）。
    """

    def __init__(self, result):
        if isinstance(result, list):
            self._results = list(result)
            self._single = None
        else:
            self._results = None
            self._single = result

    async def detect(self, query: str, workspace_id: str = "default", *, session=None):
        if self._single is not None:
            return self._single
        if not self._results:
            return _result([])
        return self._results.pop(0)


class FakeOrchestrator:
    """產出指定的 SynthesisResult；記錄被呼叫的 spec。"""

    def __init__(self, result: SynthesisResult) -> None:
        self.result = result
        self.calls: list[ToolSpec] = []

    async def synthesize(self, spec: ToolSpec) -> SynthesisResult:
        self.calls.append(spec)
        return self.result


class FakeSessionFactory:
    """sessionmaker 替代品 — yield None（FakeApprovalService 也不真的用 session）。"""

    def __call__(self):
        return _NullSessionCtx()


class _NullSessionCtx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


class FakeApprovalService:
    def __init__(self, on_approve=None) -> None:
        self.submitted: list[dict] = []
        self.approved: list[dict] = []
        self.on_approve = on_approve  # async callable(task_id) - test hook

    async def submit(self, session, *, result, workspace_id, triggered_by_query, triggered_by_user, **kwargs):
        task_id = f"syn-fake-{len(self.submitted) + 1}"
        self.submitted.append(
            {
                "task_id": task_id,
                "result": result,
                "workspace_id": workspace_id,
                "triggered_by_query": triggered_by_query,
                "triggered_by_user": triggered_by_user,
            }
        )
        return task_id

    async def approve(self, session, task_id: str, reviewer: str) -> str:
        self.approved.append({"task_id": task_id, "reviewer": reviewer})
        if self.on_approve is not None:
            await self.on_approve(task_id)
        return task_id


def _enriched(name: str, side_effect: str = "read_only") -> EnrichedToolSpec:
    return EnrichedToolSpec(
        name=name,
        description=f"desc of {name}",
        when_to_use="x",
        examples=[ConcreteExample(scenario="x", input={"celsius": 0}, output={"fahrenheit": 32.0})],
        input_fields=[FieldSpec(name="celsius", type="float", description="")],
        output_fields=[FieldSpec(name="fahrenheit", type="float", description="")],
        side_effect=side_effect,
    )


def _synth_success(name: str, side_effect: str = "read_only") -> SynthesisResult:
    return SynthesisResult(
        success=True,
        spec_raw=ToolSpec(name=name, description="d", when_to_use="x"),
        spec_enriched=_enriched(name, side_effect),
        tests="def test_x(): pass",
        final_code="class X(BaseTool): pass",
    )


def _synth_fail(name: str, err: str = "三輪都失敗") -> SynthesisResult:
    return SynthesisResult(
        success=False,
        spec_raw=ToolSpec(name=name, description="d", when_to_use="x"),
        spec_enriched=_enriched(name),
        tests="",
        error=err,
    )


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


def _agent(result, llm_responses: list[str] | None = None, **kwargs):
    return ToolAgent(
        provider=ScriptedProvider(llm_responses or []),
        gap_detector=FakeGapDetector(result),
        **kwargs,
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


# ── TA3 — 合成 path（嚴格 HITL，無 auto-approve）──────────────────────


async def test_ta3_synth_success_routes_to_approval_regardless_of_side_effect():
    """合成成功 → 一律 submit + awaiting_approval；不論 read_only 或 write_local。

    PLAN §22.5.7 紅線：LLM 生的 code 必須由人類審核才能進 registry，本層
    不做 auto-approve。
    """
    for side_effect in ("read_only", "write_local", "write_external"):
        orch = FakeOrchestrator(_synth_success("test_tool", side_effect=side_effect))
        approval = FakeApprovalService()

        agent = ToolAgent(
            provider=ScriptedProvider([]),
            gap_detector=FakeGapDetector(
                _result([_step_gap("s1", "做事", "test_tool")])
            ),
            orchestrator=orch,
            approval_service=approval,
            session_factory=FakeSessionFactory(),
        )

        out = await agent.run(_ctx(), ToolAgentInput(message=f"side_effect={side_effect}"))

        assert out.tool_called is None
        assert out.skipped_reason == "test_tool".join(
            ["awaiting_approval:", ""]
        ), f"side_effect={side_effect} should still route to approval"
        assert len(approval.submitted) == 1
        # 嚴格無 auto-approve
        assert approval.approved == []


async def test_ta3_synthesis_failure_submits_to_rescue():
    """合成失敗時：submit 仍被叫（task 進 AWAITING_HUMAN_RESCUE）；output 帶錯誤摘要。"""
    orch = FakeOrchestrator(_synth_fail("hard_tool", err="超過 3 次 sandbox 失敗"))
    approval = FakeApprovalService()

    agent = ToolAgent(
        provider=ScriptedProvider([]),
        gap_detector=FakeGapDetector(
            _result([_step_gap("s1", "難工作", "hard_tool")])
        ),
        orchestrator=orch,
        approval_service=approval,
        session_factory=FakeSessionFactory(),
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="幫我做難的工作"))

    assert out.tool_called is None
    assert out.skipped_reason.startswith("synthesis_failed")
    assert "超過 3 次" in out.skipped_reason
    assert len(approval.submitted) == 1
    assert approval.approved == []


async def test_ta3_no_synthesis_deps_falls_back_to_gap_report():
    """沒注入 orchestrator/approval → 行為退回 TA2（GAP 只 report，不觸發合成）。"""
    agent = _agent(_result([_step_gap("s1", "計算複雜統計", "advanced_stats")]))

    out = await agent.run(_ctx(), ToolAgentInput(message="算 90 天平均"))

    assert out.tool_called is None
    assert out.skipped_reason == "gap_detected"
    assert len(out.gap_specs) == 1
