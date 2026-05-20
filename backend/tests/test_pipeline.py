"""Workflow runtime smoke：用 mock provider + 內嵌 yaml workflow 跑一條 router→composer。

無論 .env 設定為何，這些測試永遠用 mock provider — 避免 CI / 本機測試耗用真實 LLM 額度。
"""

import pytest
import yaml

from app.agents import registry as agent_registry
from app.agents.composer import ComposerAgent
from app.agents.router import RouterAgent
from app.providers.mock import MockProvider
from app.workflow.runtime import run_workflow
from app.workflow.spec import WorkflowDef


@pytest.fixture(autouse=True)
def _bootstrap():
    agent_registry.clear()
    provider = MockProvider()
    agent_registry.register(RouterAgent(provider=provider))
    agent_registry.register(ComposerAgent(provider=provider))


_WORKFLOW_YAML = """
id: test_v1
workspace: test
description: pipeline test
steps:
  - id: router
    agent: router
    input:
      message: $event.message
      history: $context.history

  - id: composer
    agent: composer
    input:
      message: $event.message
      intent: $router

emit:
  draft: $composer.text
  citations: $composer.citations
"""


async def test_workflow_runs_router_then_composer():
    wf = WorkflowDef.model_validate(yaml.safe_load(_WORKFLOW_YAML))
    result = await run_workflow(
        wf,
        event={"message": "70 歲可以申請車貸嗎？"},
        workspace_id="test",
        room_id="r1",
        history=[],
    )
    assert result.workflow_id == "test_v1"
    assert [s.step_id for s in result.steps] == ["router", "composer"]
    router_step = result.steps[0]
    composer_step = result.steps[1]
    assert router_step.error is None
    assert router_step.output["category"] == "loan"
    assert composer_step.error is None
    assert result.emit.get("draft")
    assert "draft" in result.emit and "citations" in result.emit


async def test_workflow_unknown_intent_falls_back():
    wf = WorkflowDef.model_validate(yaml.safe_load(_WORKFLOW_YAML))
    result = await run_workflow(
        wf,
        event={"message": "今天天氣不錯"},
        workspace_id="test",
        room_id="r2",
        history=[],
    )
    router_step = result.steps[0]
    assert router_step.output["category"] == "general"
    assert result.emit.get("draft")


_HALT_WORKFLOW_YAML = """
id: halt_v1
workspace: test_cs
description: router halt when out of scope
steps:
  - id: router
    agent: router
    input:
      message: $event.message
      history: $context.history
    halt_when_false: $router.in_scope
    halt_emit:
      draft: $router.scope_refusal_text
      citations: []

  - id: composer
    agent: composer
    input:
      message: $event.message
      intent: $router

emit:
  draft: $composer.text
  citations: $composer.citations
"""


async def test_workflow_halts_when_router_out_of_scope(monkeypatch):
    """router 判定 out-of-scope → composer 不該跑，emit 用 halt_emit。"""
    from app.workflow import workspace_registry

    # 注入一個只接 loan/complaint/general 的 workspace；HR 訊息會被擋
    monkeypatch.setitem(
        workspace_registry._REGISTRY,
        "test_cs",
        {
            "id": "test_cs",
            "display_name": "客服測試",
            "allowed_categories": ["loan", "complaint", "general"],
        },
    )

    wf = WorkflowDef.model_validate(yaml.safe_load(_HALT_WORKFLOW_YAML))
    result = await run_workflow(
        wf,
        event={"message": "我可以休幾天特休？"},  # mock 會判 hr
        workspace_id="test_cs",
        room_id="r3",
        history=[],
    )

    assert [s.step_id for s in result.steps] == ["router"]  # composer 沒跑
    router_step = result.steps[0]
    assert router_step.output["category"] == "hr"
    assert router_step.output["in_scope"] is False
    assert "hr" in result.emit["draft"]
    assert "客服測試" in result.emit["draft"]
    assert result.emit["citations"] == []


async def test_workflow_does_not_halt_when_router_in_scope(monkeypatch):
    """router 判定 in-scope → 整條 workflow 照跑，emit 走 workflow.emit。"""
    from app.workflow import workspace_registry

    monkeypatch.setitem(
        workspace_registry._REGISTRY,
        "test_cs",
        {
            "id": "test_cs",
            "display_name": "客服測試",
            "allowed_categories": ["loan", "complaint", "general"],
        },
    )

    wf = WorkflowDef.model_validate(yaml.safe_load(_HALT_WORKFLOW_YAML))
    result = await run_workflow(
        wf,
        event={"message": "70 歲可以申請車貸嗎？"},
        workspace_id="test_cs",
        room_id="r4",
        history=[],
    )

    assert [s.step_id for s in result.steps] == ["router", "composer"]
    assert result.steps[0].output["in_scope"] is True
    assert result.emit.get("draft")  # composer 的輸出，不是 halt_emit
