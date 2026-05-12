"""Phase 6 agents 測試 — 用 mock provider 驗證型別正確且優雅降級。

MockProvider 對非 router 的 JSON 提示會回 router 樣式的 JSON（不符合各 agent schema），
所以這些測試主要驗證：
1. agent 不會 crash
2. 回傳值符合 output_schema
3. 解析失敗時降級到 sensible defaults
"""

from __future__ import annotations

import pytest

from app.agents.clause_analyzer import ClauseAnalyzerAgent
from app.agents.policy import PolicyAgent
from app.agents.risk import RiskAgent
from app.agents.tone import ToneAgent
from app.providers.mock import MockProvider
from app.schemas.agent import (
    AgentContext,
    ClauseAnalyzerInput,
    PolicyInput,
    RiskInput,
    RouterOutput,
    ToneInput,
)


@pytest.fixture
def ctx():
    return AgentContext(
        workspace_id="test",
        room_id="r1",
        trace_id="t1",
        history=[],
    )


async def test_policy_agent_returns_schema(ctx):
    agent = PolicyAgent(MockProvider())
    out = await agent.run(
        ctx,
        PolicyInput(
            message="高齡客戶申請車貸",
            intent=RouterOutput(intent="loan_inquiry", category="loan"),
            category="loan",
        ),
    )
    assert isinstance(out.violations, list)
    assert isinstance(out.citations, list)
    assert isinstance(out.compliance_note, str)


async def test_tone_agent_falls_back_to_professional(ctx):
    agent = ToneAgent(MockProvider())
    out = await agent.run(ctx, ToneInput(message="hi"))
    # Mock 回的 router-style JSON 無法對應 tone schema → fallback
    assert out.tone == "professional"


async def test_risk_agent_falls_back_to_low(ctx):
    agent = RiskAgent(MockProvider())
    out = await agent.run(ctx, RiskInput(message="hi"))
    assert out.risk_level == "low"
    assert isinstance(out.reasons, list)


async def test_clause_analyzer_falls_back_to_general(ctx):
    agent = ClauseAnalyzerAgent(MockProvider())
    out = await agent.run(ctx, ClauseAnalyzerInput(message="NDA 條款怎麼寫？"))
    assert out.clause_type == "general_inquiry"
    assert out.risk_level == "low"
    assert isinstance(out.key_points, list)
