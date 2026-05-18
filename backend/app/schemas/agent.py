from typing import Any

from pydantic import BaseModel, Field


class AgentContext(BaseModel):
    """傳遞給每個 Agent 的執行上下文。"""

    workspace_id: str = "default"
    room_id: str
    trace_id: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)


class AgentStepResult(BaseModel):
    """單一 agent 執行紀錄，會累積成 AgentTrace.steps。"""

    step_id: str
    agent_id: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    error: str | None = None
    latency_ms: int = 0
    model: str | None = None


class RouterInput(BaseModel):
    message: str
    history: list[dict[str, Any]] = Field(default_factory=list)


class RouterOutput(BaseModel):
    intent: str
    category: str


class ComposerInput(BaseModel):
    message: str
    intent: RouterOutput | None = None
    docs: list[dict[str, Any]] = Field(default_factory=list)
    tone: str | None = None
    tone_rationale: str | None = None
    policy: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    clause_analysis: dict[str, Any] | None = None
    ticket: dict[str, Any] | None = None
    # TA5：tool_agent 命中工具時的結果；composer 看到這個會優先採用而非走 RAG。
    tool_result: dict[str, Any] | None = None
    tool_called: str | None = None


class ComposerOutput(BaseModel):
    text: str
    citations: list[dict[str, Any]] = Field(default_factory=list)


# Phase 6 — Policy / Tone / Risk / TicketDecision / ClauseAnalyzer
class PolicyInput(BaseModel):
    message: str = ""
    intent: RouterOutput | None = None
    category: str = ""


class PolicyOutput(BaseModel):
    violations: list[str] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    compliance_note: str = ""


class ToneInput(BaseModel):
    message: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    intent: RouterOutput | None = None


class ToneOutput(BaseModel):
    tone: str  # empathetic | professional | direct | cautious | apologetic
    rationale: str = ""


class RiskInput(BaseModel):
    message: str = ""
    intent: RouterOutput | None = None
    docs: list[dict[str, Any]] = Field(default_factory=list)


class RiskOutput(BaseModel):
    risk_level: str = "low"  # low | medium | high
    reasons: list[str] = Field(default_factory=list)


class TicketDecisionInput(BaseModel):
    message: str
    intent: RouterOutput | None = None
    solution_text: str = ""


class TicketDecisionOutput(BaseModel):
    should_create_ticket: bool = False
    summary: str = ""
    rationale: str = ""
    ticket_id: str | None = None


class ClauseAnalyzerInput(BaseModel):
    message: str
    history: list[dict[str, Any]] = Field(default_factory=list)


class ClauseAnalyzerOutput(BaseModel):
    clause_type: str = "general_inquiry"
    risk_level: str = "low"
    suggestion: str = ""
    key_points: list[str] = Field(default_factory=list)


# TA1：tool_agent — 對 user message 做 retrieval，命中就呼叫；
# TA2 起會接上 gap_detector + 合成。
class ToolAgentInput(BaseModel):
    message: str
    intent: RouterOutput | None = None


class ToolAgentOutput(BaseModel):
    tool_called: str | None = None  # tool_id；None 表示這條路徑沒呼叫工具
    tool_result: dict[str, Any] | None = None  # tool 回傳值（model_dump）
    candidates: list[dict[str, Any]] = Field(default_factory=list)  # retrieval 觀測
    skipped_reason: str | None = None  # 沒呼叫的原因（觀測用，給 trace 看）
    error: str | None = None  # 呼叫過程出錯時的訊息
    # TA2：gap_detector 偵測出的 GAP step（給 TA3 觸發 synthesis 用）
    gap_specs: list[dict[str, Any]] = Field(default_factory=list)
