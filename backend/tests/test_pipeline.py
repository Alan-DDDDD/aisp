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
