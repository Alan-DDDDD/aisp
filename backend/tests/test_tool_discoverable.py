"""ToolRetriever skips agent-internal (discoverable=False) tools.

確保 kb_search 之類由特定 agent 內部呼叫的工具，不會被 tool_agent / gap_detector
經由 retrieval 誤選。
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agents.composer import _is_effectively_empty
from app.synthesis.tool_retriever import ToolRetriever
from app.tools import registry as tool_registry
from app.tools.base import BaseTool, SideEffect


class _Inp(BaseModel):
    x: int


class _Out(BaseModel):
    y: int


class _PublicTool(BaseTool):
    id = "public_tool"
    description = "公開可用的工具：將平方公尺轉換為坪"
    when_to_use = "需要將平方公尺轉換為坪"
    input_schema = _Inp
    output_schema = _Out
    side_effect = SideEffect.READ_ONLY
    discoverable = True

    async def call(self, ctx, payload):
        return _Out(y=payload.x)


class _InternalTool(BaseTool):
    id = "internal_tool"
    description = "內部工具：將平方公尺轉換為坪（kb_search 風格）"
    when_to_use = "agent 內部呼叫，使用者問什麼都不該被選到"
    input_schema = _Inp
    output_schema = _Out
    side_effect = SideEffect.READ_ONLY
    discoverable = False

    async def call(self, ctx, payload):
        return _Out(y=payload.x)


@pytest.fixture(autouse=True)
def _isolate_registry():
    tool_registry.clear()
    yield
    tool_registry.clear()


async def test_retrieve_skips_non_discoverable_tools():
    """即使 internal_tool 在 registry，retrieve() 也不該回傳它。"""
    tool_registry.register(_PublicTool())
    tool_registry.register(_InternalTool())

    retriever = ToolRetriever()
    retriever.build()  # 兩個都會進 embedding index
    candidates = retriever.retrieve(
        "將 100 平方公尺轉換為坪",
        top_k=5,
        workspace_id="cs",
    )

    cand_ids = [c.tool_id for c in candidates]
    assert "public_tool" in cand_ids
    assert "internal_tool" not in cand_ids


# ── composer._is_effectively_empty ──────────────────────────────────


def test_empty_dict_is_empty():
    assert _is_effectively_empty({})


def test_none_is_empty():
    assert _is_effectively_empty(None)


def test_empty_string_is_empty():
    assert _is_effectively_empty("")
    assert _is_effectively_empty("   ")


def test_empty_list_is_empty():
    assert _is_effectively_empty([])


def test_kb_search_empty_docs_is_empty():
    """kb_search 回空時：docs=[] + metadata fields，應視為空。"""
    assert _is_effectively_empty(
        {"docs": [], "kb_name": "faq", "query": "問了什麼"}
    )


def test_dict_with_real_payload_is_not_empty():
    assert not _is_effectively_empty({"fahrenheit": 89.6})
    assert not _is_effectively_empty(
        {"docs": [{"title": "車貸", "score": 0.8}], "kb_name": "faq"}
    )


def test_all_metadata_only_is_empty():
    """整個 dict 都只有 query/kb_name 這種 metadata，沒實質結果。"""
    assert _is_effectively_empty({"query": "x", "kb_name": "faq"})


def test_zero_number_is_not_empty():
    """0 是合法計算結果，不該被視為空。"""
    assert not _is_effectively_empty({"result": 0})
    assert not _is_effectively_empty({"fahrenheit": 0.0})
