"""TA1 — ToolAgent 單元測試。

涵蓋路徑：
  - no candidates → skipped_reason=no_candidates
  - low similarity → skipped_reason 帶 similarity 數字
  - high similarity 但 registry 沒有該 tool → tool_missing_from_registry
  - arg gen 回 _error → skipped_reason=arg_gen_missing
  - arg gen 回正確 args → 呼叫 tool → tool_result 含預期值
  - tool.call 拋例外 → error 欄位帶錯誤訊息
  - input validation 失敗 → skipped_reason=input_validation
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agents.tool_agent import ToolAgent
from app.schemas.agent import AgentContext, ToolAgentInput
from app.synthesis.schemas import ToolCandidate
from app.tools import registry as tool_registry
from app.tools.base import BaseTool, SideEffect
from tests._fakes import FakeRetriever, ScriptedProvider


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


@pytest.fixture(autouse=True)
def _isolate_registry():
    tool_registry.clear()
    yield
    tool_registry.clear()


def _ctx() -> AgentContext:
    return AgentContext(workspace_id="cs", room_id="r", trace_id="t")


# ── tests ───────────────────────────────────────────────────────────


async def test_no_candidates_skips_call():
    retriever = FakeRetriever()  # 空 mapping
    agent = ToolAgent(provider=ScriptedProvider([]), retriever=retriever)

    out = await agent.run(_ctx(), ToolAgentInput(message="現在幾度?"))

    assert out.tool_called is None
    assert out.skipped_reason == "no_candidates"
    assert out.candidates == []


async def test_low_similarity_skips_call():
    retriever = FakeRetriever()
    retriever.set(
        "天氣如何",
        [ToolCandidate(tool_id="celsius_to_fahrenheit", similarity=0.30, description="d")],
    )
    agent = ToolAgent(provider=ScriptedProvider([]), retriever=retriever)

    out = await agent.run(_ctx(), ToolAgentInput(message="天氣如何"))

    assert out.tool_called is None
    assert out.skipped_reason.startswith("low_similarity")
    assert len(out.candidates) == 1


async def test_high_similarity_but_tool_missing():
    retriever = FakeRetriever()
    retriever.set(
        "攝氏 30 度轉華氏",
        [ToolCandidate(tool_id="ghost_tool", similarity=0.85, description="d")],
    )
    agent = ToolAgent(provider=ScriptedProvider([]), retriever=retriever)

    out = await agent.run(_ctx(), ToolAgentInput(message="攝氏 30 度轉華氏"))

    assert out.tool_called is None
    assert out.skipped_reason == "tool_missing_from_registry"


async def test_happy_path_calls_tool():
    tool_registry.register(_CelsiusTool())
    retriever = FakeRetriever()
    retriever.set(
        "攝氏 32 度是華氏幾度",
        [ToolCandidate(tool_id="celsius_to_fahrenheit", similarity=0.78, description="d")],
    )
    agent = ToolAgent(
        provider=ScriptedProvider(['{"celsius": 32}']),
        retriever=retriever,
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="攝氏 32 度是華氏幾度"))

    assert out.tool_called == "celsius_to_fahrenheit"
    assert out.tool_result == {"fahrenheit": 32 * 9 / 5 + 32}
    assert out.skipped_reason is None
    assert out.error is None


async def test_arg_gen_missing_required():
    tool_registry.register(_CelsiusTool())
    retriever = FakeRetriever()
    retriever.set(
        "幫我轉換溫度",
        [ToolCandidate(tool_id="celsius_to_fahrenheit", similarity=0.70, description="d")],
    )
    agent = ToolAgent(
        provider=ScriptedProvider(['{"_error": "missing field: celsius"}']),
        retriever=retriever,
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="幫我轉換溫度"))

    assert out.tool_called is None
    assert out.skipped_reason.startswith("arg_gen_missing")


async def test_input_validation_fails():
    tool_registry.register(_CelsiusTool())
    retriever = FakeRetriever()
    retriever.set(
        "轉換 abc 度",
        [ToolCandidate(tool_id="celsius_to_fahrenheit", similarity=0.70, description="d")],
    )
    # LLM 回不合法的 type（celsius 是 float，給了 dict）
    agent = ToolAgent(
        provider=ScriptedProvider(['{"celsius": {"bad": "type"}}']),
        retriever=retriever,
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="轉換 abc 度"))

    assert out.tool_called is None
    assert out.skipped_reason.startswith("input_validation")


async def test_tool_call_failure_captured():
    tool_registry.register(_BoomTool())
    retriever = FakeRetriever()
    retriever.set(
        "炸一下",
        [ToolCandidate(tool_id="always_boom", similarity=0.90, description="d")],
    )
    agent = ToolAgent(
        provider=ScriptedProvider(['{"celsius": 10}']),
        retriever=retriever,
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="炸一下"))

    assert out.tool_called == "always_boom"
    assert out.error is not None
    assert "simulated tool failure" in out.error
    assert out.tool_result is None


async def test_arg_gen_unparseable_response():
    tool_registry.register(_CelsiusTool())
    retriever = FakeRetriever()
    retriever.set(
        "x",
        [ToolCandidate(tool_id="celsius_to_fahrenheit", similarity=0.70, description="d")],
    )
    agent = ToolAgent(
        provider=ScriptedProvider(["totally not json 完全壞掉"]),
        retriever=retriever,
    )

    out = await agent.run(_ctx(), ToolAgentInput(message="x"))

    assert out.tool_called is None
    assert out.skipped_reason == "arg_gen_unparseable"
