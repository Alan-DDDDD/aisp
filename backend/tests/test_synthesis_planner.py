"""Phase 6 M2 — Planner LLM 解析行為。"""

from __future__ import annotations

from app.synthesis.planner import Planner
from tests._fakes import ScriptedProvider


async def test_planner_parses_well_formed_json():
    provider = ScriptedProvider([
        '{"steps": ['
        '{"id": "s1", "description": "查客戶 C-123 的訂單", "requires_tool": true},'
        '{"id": "s2", "description": "把結果整理成回覆給使用者", "requires_tool": false}'
        ']}',
    ])
    planner = Planner(provider=provider)
    result = await planner.plan("查客戶 C-123 的訂單並回覆")

    assert len(result.steps) == 2
    assert result.steps[0].id == "s1"
    assert result.steps[0].requires_tool is True
    assert result.steps[1].requires_tool is False


async def test_planner_handles_code_fence():
    """LLM 常忍不住加 ```json 圍欄，parse_json_loose 要救得回來。"""
    provider = ScriptedProvider([
        '```json\n{"steps": [{"id": "s1", "description": "x", "requires_tool": true}]}\n```',
    ])
    planner = Planner(provider=provider)
    result = await planner.plan("x")
    assert len(result.steps) == 1
    assert result.steps[0].id == "s1"


async def test_planner_falls_back_on_garbage():
    """LLM 出包時不該整條 pipeline 斷掉；應保守把 query 當單一 step。"""
    provider = ScriptedProvider(["this is not json at all"])
    planner = Planner(provider=provider)
    result = await planner.plan("某個查詢")
    assert len(result.steps) == 1
    assert result.steps[0].description == "某個查詢"
    assert result.steps[0].requires_tool is True


async def test_planner_uses_configured_model():
    """確認 GenerationRequest.model 真的有帶上（M1 的 routing 機制）。"""
    provider = ScriptedProvider(['{"steps": []}'])
    planner = Planner(provider=provider, model="custom-70b")
    await planner.plan("x")
    assert provider.calls[0].model == "custom-70b"
