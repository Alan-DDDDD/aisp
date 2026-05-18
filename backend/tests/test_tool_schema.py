"""Phase 6 M1 — BaseTool schema 重構驗證。

確認：
- 既有 builtin tools 都填上了 when_to_use / when_NOT_to_use / examples / side_effect / tags
- ToolExample / SideEffect 型別正確
- embedding_text() 產出包含關鍵欄位的文字表徵（給 retrieval 用）
"""

from __future__ import annotations

from app.tools.base import BaseTool, SideEffect, ToolExample
from app.tools.kb_search import KBSearchTool
from app.tools.ticket_create import TicketCreateTool

BUILTIN_TOOLS: list[type[BaseTool]] = [KBSearchTool, TicketCreateTool]


def test_builtin_tools_have_phase6_metadata():
    """所有 builtin tool 都必須提供 Phase 6 新增欄位的非空內容。"""
    for tool_cls in BUILTIN_TOOLS:
        assert tool_cls.id, f"{tool_cls.__name__} 缺 id"
        assert tool_cls.description, f"{tool_cls.__name__} 缺 description"
        assert tool_cls.when_to_use, f"{tool_cls.__name__} 缺 when_to_use"
        assert tool_cls.when_NOT_to_use, f"{tool_cls.__name__} 缺 when_NOT_to_use"
        assert tool_cls.examples, f"{tool_cls.__name__} 缺 examples"
        assert tool_cls.tags, f"{tool_cls.__name__} 缺 tags"
        assert isinstance(tool_cls.side_effect, SideEffect)
        assert tool_cls.source == "builtin"


def test_examples_are_tool_example_instances():
    for tool_cls in BUILTIN_TOOLS:
        for ex in tool_cls.examples:
            assert isinstance(ex, ToolExample)
            assert ex.scenario


def test_kb_search_classification():
    assert KBSearchTool.side_effect is SideEffect.READ_ONLY
    assert KBSearchTool.requires_approval is False
    assert "knowledge" in KBSearchTool.tags


def test_ticket_create_classification():
    # demo 用本地 SQLite，故為 WRITE_LOCAL；對接 Jira 時要升級
    assert TicketCreateTool.side_effect is SideEffect.WRITE_LOCAL
    assert "ticket" in TicketCreateTool.tags


def test_embedding_text_contains_key_fields():
    text = KBSearchTool.embedding_text()
    # 標題 + 五個關鍵段落都要在
    assert "[Tool: kb_search]" in text
    assert "Description:" in text
    assert "Use when:" in text
    assert "Don't use when:" in text
    assert "Examples:" in text
    assert "Side effect: read_only" in text


def test_embedding_text_includes_scenarios():
    """範例的 scenario 文字會進入 embedding，影響檢索品質。"""
    text = TicketCreateTool.embedding_text()
    scenarios = [ex.scenario for ex in TicketCreateTool.examples]
    for s in scenarios:
        assert s in text
