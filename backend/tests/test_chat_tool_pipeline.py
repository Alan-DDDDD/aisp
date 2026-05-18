"""TA6 — e2e：workflow runtime + tool_agent + composer 三者接線驗證。

不測 gap_detector 內部 cascading（tool_agent 自己的測試已涵蓋），這裡的重點：
  - YAML `$tool_agent.tool_called` / `$tool_agent.tool_result` 能被 resolver 正確解析
  - ComposerInput.tool_called / tool_result 收到值
  - 命中 tool 時 composer 把 tool_result 寫進回覆，沒命中時走原本 RAG 流程
"""

from __future__ import annotations

import pytest
import yaml
from pydantic import BaseModel

from app.agents import registry as agent_registry
from app.agents.base import BaseAgent
from app.agents.composer import ComposerAgent
from app.agents.router import RouterAgent
from app.providers.mock import MockProvider
from app.schemas.agent import (
    AgentContext,
    ComposerInput,
    ComposerOutput,
    ToolAgentInput,
    ToolAgentOutput,
)
from app.workflow.runtime import run_workflow
from app.workflow.spec import WorkflowDef


# ── Fake ToolAgent ──────────────────────────────────────────────────


class _FakeToolAgent(BaseAgent):
    """測試用：直接回 canned ToolAgentOutput，不跑 retrieval / arg_gen / tool。"""

    id = "tool_agent"
    input_schema = ToolAgentInput
    output_schema = ToolAgentOutput

    def __init__(self, output: ToolAgentOutput) -> None:
        self.output = output
        self.calls: list[ToolAgentInput] = []

    async def run(self, ctx: AgentContext, payload: ToolAgentInput) -> ToolAgentOutput:  # type: ignore[override]
        self.calls.append(payload)
        return self.output


# ── 共用 — 簡化的 cs-like workflow（去掉 knowledge / policy / tone）──────


_WORKFLOW_YAML = """
id: chat_tool_test
workspace: test
description: "e2e router→tool_agent→composer"
steps:
  - id: router
    agent: router
    input:
      message: $event.message
      history: $context.history

  - id: tool_agent
    agent: tool_agent
    input:
      message: $event.message
      intent: $router

  - id: composer
    agent: composer
    input:
      message: $event.message
      intent: $router
      tool_called: $tool_agent.tool_called
      tool_result: $tool_agent.tool_result

emit:
  draft: $composer.text
  tool: $tool_agent
"""


# ── 攔截 composer 的 LLM call，驗證 system prompt 含 tool_result ──────


class _RecordingComposer(ComposerAgent):
    """攔截 system prompt + 回 fixed text，方便驗證上下文。"""

    def __init__(self):
        provider = _RecordingProvider()
        super().__init__(provider=provider)
        self.provider: _RecordingProvider  # type: ignore[assignment]

    @property
    def last_system(self) -> str:
        return self.provider.last_system


class _RecordingProvider(MockProvider):
    def __init__(self) -> None:
        self.last_system: str = ""

    async def generate(self, req):
        self.last_system = req.system or ""
        return await super().generate(req)


# ── tests ───────────────────────────────────────────────────────────


@pytest.fixture
def _bootstrap_with_tool(monkeypatch):
    """工廠：用指定的 tool_agent output 建立 agent_registry 並回傳 composer 給驗證。"""

    def _build(tool_output: ToolAgentOutput) -> _RecordingComposer:
        agent_registry.clear()
        composer = _RecordingComposer()
        agent_registry.register(RouterAgent(provider=MockProvider()))
        agent_registry.register(_FakeToolAgent(tool_output))
        agent_registry.register(composer)
        return composer

    return _build


async def test_tool_hit_passes_result_to_composer(_bootstrap_with_tool):
    composer = _bootstrap_with_tool(
        ToolAgentOutput(
            tool_called="celsius_to_fahrenheit",
            tool_result={"fahrenheit": 89.6},
        )
    )
    wf = WorkflowDef.model_validate(yaml.safe_load(_WORKFLOW_YAML))

    result = await run_workflow(
        wf,
        event={"message": "攝氏 32 度是華氏幾度？"},
        workspace_id="test",
        room_id="r1",
        history=[],
    )

    # 三個 step 都跑且 composer 拿到 tool_result
    step_ids = [s.step_id for s in result.steps]
    assert "tool_agent" in step_ids
    assert "composer" in step_ids
    assert all(s.error is None for s in result.steps)

    # composer 的 system prompt 含 [TOOL_RESULT] 區塊與 tool_id / output
    assert "[TOOL_RESULT]" in composer.last_system
    assert "celsius_to_fahrenheit" in composer.last_system
    assert "89.6" in composer.last_system
    # 而且不是 fallback「沒有相關資訊」訊息
    assert "知識庫中沒有相關資訊" not in result.emit["draft"]


async def test_no_tool_falls_through_to_composer(_bootstrap_with_tool):
    """tool_agent 沒命中時 composer 走原本流程，system prompt 上下文不含 tool 區塊。"""
    composer = _bootstrap_with_tool(
        ToolAgentOutput(tool_called=None, tool_result=None, skipped_reason="no_tool_needed")
    )
    wf = WorkflowDef.model_validate(yaml.safe_load(_WORKFLOW_YAML))

    result = await run_workflow(
        wf,
        event={"message": "今天天氣不錯"},
        workspace_id="test",
        room_id="r2",
        history=[],
    )

    # 用 `工具結果（` 帶括號當 marker — composer prompt 守則本身會提到「工具結果」
    # 但只有 _build_context 寫 tool 區塊時才會用 `工具結果（{tool_id}）` 這個格式
    # 用閉合 tag 當 marker — 只會出現在 _build_context 實際注入的 block，
    # 不會出現在 system prompt 的規則文字中（規則只提開頭 tag）
    assert "[/TOOL_RESULT]" not in composer.last_system
    # emit.tool 仍會有 — 給前端 badge / debug 用
    assert result.emit["tool"]["skipped_reason"] == "no_tool_needed"


async def test_tool_with_error_doesnt_break_pipeline(_bootstrap_with_tool):
    """tool_called 有值但有 error 時，composer 不會 crash（tool_result 為 None）。"""
    composer = _bootstrap_with_tool(
        ToolAgentOutput(
            tool_called="boom_tool",
            tool_result=None,
            error="tool_call_failed:RuntimeError",
        )
    )
    wf = WorkflowDef.model_validate(yaml.safe_load(_WORKFLOW_YAML))

    result = await run_workflow(
        wf,
        event={"message": "炸一下"},
        workspace_id="test",
        room_id="r3",
        history=[],
    )

    composer_step = next(s for s in result.steps if s.step_id == "composer")
    assert composer_step.error is None  # composer 仍正常產出
    # tool_called 有值但 tool_result 是 None — composer 應該忽略（不寫 tool 區塊）
    # 用閉合 tag 當 marker — 只會出現在 _build_context 實際注入的 block，
    # 不會出現在 system prompt 的規則文字中（規則只提開頭 tag）
    assert "[/TOOL_RESULT]" not in composer.last_system
