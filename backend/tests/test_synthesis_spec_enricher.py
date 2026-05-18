"""Phase 6 M4 — Spec Enricher 行為。"""

from __future__ import annotations

from app.synthesis.schemas import ToolSpec
from app.synthesis.spec_enricher import SpecEnricher
from tests._fakes import ScriptedProvider

_GOOD_JSON = """
{
  "name": "get_orders_recent",
  "description": "查客戶近 N 天訂單",
  "when_to_use": "查單一客戶在特定時間範圍內的訂單",
  "when_not_to_use": "不要用於跨客戶彙總",
  "examples": [
    {
      "scenario": "查 C-123 近 30 天",
      "input": {"customer_id": "C-123", "days": 30},
      "output": {"orders": [], "total": 0}
    },
    {
      "scenario": "查 C-456 近 7 天",
      "input": {"customer_id": "C-456", "days": 7},
      "output": {"orders": [], "total": 0}
    }
  ],
  "input_fields": [
    {"name": "customer_id", "type": "str", "description": "客戶 ID", "required": true},
    {"name": "days", "type": "int", "description": "天數", "required": false, "default": 30}
  ],
  "output_fields": [
    {"name": "orders", "type": "list", "description": "訂單"},
    {"name": "total", "type": "int", "description": "筆數"}
  ],
  "side_effect": "read_only",
  "tags": ["customer", "orders"]
}
"""


async def test_enricher_parses_good_json():
    provider = ScriptedProvider([_GOOD_JSON])
    enricher = SpecEnricher(provider=provider)
    raw = ToolSpec(
        name="get_orders_recent", description="查客戶近 N 天訂單", when_to_use="..."
    )
    enriched = await enricher.enrich(raw)

    assert enriched.name == "get_orders_recent"
    assert len(enriched.examples) == 2
    assert {f.name for f in enriched.input_fields} == {"customer_id", "days"}
    assert {f.name for f in enriched.output_fields} == {"orders", "total"}
    assert enriched.side_effect == "read_only"


async def test_enricher_falls_back_on_garbage():
    """LLM 出包時應產出 minimal 但 valid 的 EnrichedToolSpec，不要直接 crash。"""
    provider = ScriptedProvider(["this is not JSON"])
    enricher = SpecEnricher(provider=provider)
    raw = ToolSpec(name="foo", description="bar", when_to_use="baz")
    enriched = await enricher.enrich(raw)

    assert enriched.name == "foo"
    assert enriched.description == "bar"
    assert enriched.input_fields  # 至少 1 個欄位
    assert enriched.output_fields
    assert "請人類補上" in enriched.when_not_to_use


async def test_enricher_preserves_raw_name_if_missing_in_output():
    """LLM 忘了帶 name 時，應沿用 raw spec 的 name。"""
    # 缺 name 的 JSON
    provider = ScriptedProvider([
        '{"description": "x", "when_to_use": "x",'
        ' "input_fields": [{"name": "q", "type": "str", "description": ""}],'
        ' "output_fields": [{"name": "r", "type": "dict", "description": ""}]}'
    ])
    enricher = SpecEnricher(provider=provider)
    raw = ToolSpec(name="original_name", description="d", when_to_use="w")
    enriched = await enricher.enrich(raw)
    assert enriched.name == "original_name"
