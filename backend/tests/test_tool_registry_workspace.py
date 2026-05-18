"""Phase 6 M6 — tool_registry workspace scoping。"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.schemas.agent import AgentContext
from app.tools import registry
from app.tools.base import BaseTool, SideEffect, ToolExample


class _DummyIn(BaseModel):
    x: str = ""


class _DummyOut(BaseModel):
    y: str = ""


def _make_tool(tool_id: str):
    """工廠：每次 new 一個 class 避免不同 test 互相污染。"""

    class _DummyTool(BaseTool):
        id = tool_id
        version = "1.0.0"
        source = "builtin"
        description = "dummy"
        when_to_use = "test"
        when_NOT_to_use = "n/a"
        examples = [ToolExample(scenario="x", input={}, output={})]
        input_schema = _DummyIn
        output_schema = _DummyOut
        side_effect = SideEffect.READ_ONLY
        tags = ["test"]

        async def call(self, ctx: AgentContext, payload: _DummyIn) -> _DummyOut:
            return _DummyOut()

    _DummyTool.__name__ = f"_DummyTool_{tool_id}"
    return _DummyTool()


@pytest.fixture(autouse=True)
def _clean():
    registry.clear()
    yield
    registry.clear()


def test_default_register_is_global():
    registry.register(_make_tool("foo"))
    assert registry.workspace_of("foo") is None


def test_register_with_workspace():
    registry.register(_make_tool("hr_tool"), workspace_id="hr")
    assert registry.workspace_of("hr_tool") == "hr"


def test_list_for_workspace_includes_global_and_own():
    registry.register(_make_tool("global_one"))
    registry.register(_make_tool("hr_one"), workspace_id="hr")
    registry.register(_make_tool("cs_one"), workspace_id="cs")

    hr_visible = registry.list_for_workspace("hr")
    assert "global_one" in hr_visible
    assert "hr_one" in hr_visible
    assert "cs_one" not in hr_visible


def test_list_for_workspace_none_returns_only_global():
    registry.register(_make_tool("global_one"))
    registry.register(_make_tool("hr_one"), workspace_id="hr")

    visible = registry.list_for_workspace(None)
    assert "global_one" in visible
    assert "hr_one" not in visible


def test_unregister():
    registry.register(_make_tool("doomed"))
    assert registry.unregister("doomed") is True
    assert registry.unregister("doomed") is False
    assert "doomed" not in registry.list_ids()
