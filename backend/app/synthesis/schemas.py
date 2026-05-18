"""Phase 6 synthesis 共用型別。

設計上分兩層：
1. Planner / Judge 的 wire schema（強制 LLM 輸出 JSON 要對得上）
2. 內部 domain schema（Step / StepDecision / GapDetectionResult）

兩層分開的好處：LLM 寫錯欄位時可以在解析時就被擋下來，不會污染下游流程。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

# ── 共用列舉 ─────────────────────────────────────────────────────────


class DecisionType(StrEnum):
    """Step 的最終決策。"""

    USE = "USE"
    COMPOSE = "COMPOSE"
    GAP = "GAP"


class DecisionRoute(StrEnum):
    """決策走的路徑（給 audit / debugging 用）。"""

    SHORTCUT_HIGH = "shortcut_high"   # 相似度 >= gap_sim_high，直接 USE
    SHORTCUT_LOW = "shortcut_low"     # 相似度 <= gap_sim_low，直接 GAP
    JUDGE = "judge"                   # 灰色區，跑 judge LLM
    HUMAN = "human"                   # judge confidence 仍灰，問人類
    NO_TOOL_NEEDED = "no_tool_needed"  # planner 標 requires_tool=false


# ── Planner wire schema ─────────────────────────────────────────────


class PlannerStep(BaseModel):
    """Planner LLM 輸出的單一 step。"""

    id: str
    description: str
    requires_tool: bool


class PlannerOutput(BaseModel):
    """Planner LLM 的完整輸出。"""

    steps: list[PlannerStep] = Field(default_factory=list)


# ── Tool retrieval ──────────────────────────────────────────────────


class ToolCandidate(BaseModel):
    """Retrieval 找出的候選工具，包含相似度與必要 metadata。"""

    tool_id: str
    similarity: float
    description: str
    when_to_use: str = ""
    when_not_to_use: str = ""
    side_effect: str = "read_only"


# ── Tool spec（GAP 時要產出的「需要什麼樣的工具」規格）─────────────


class ToolSpec(BaseModel):
    """新工具的規格。Planner 或 Judge 在判 GAP 時要產出這個。

    M2 階段先收集核心欄位，Code Agent（M4）會基於這個再做 spec 補完。
    """

    name: str  # 建議的 tool_id
    description: str
    when_to_use: str = ""
    when_not_to_use: str = ""
    input_hint: str = ""  # 自然語言描述需要哪些 input 欄位
    output_hint: str = ""  # 自然語言描述要回什麼
    examples: list[dict[str, Any]] = Field(default_factory=list)


# ── Enriched spec（M4 Spec Enricher 的輸出）─────────────────────────


class FieldSpec(BaseModel):
    """單一 Pydantic 欄位的描述。Code Agent 拿來組裝 BaseModel。"""

    name: str
    type: str  # str | int | float | bool | list | dict | str | None | datetime
    description: str = ""
    required: bool = True
    default: Any = None  # required=False 時可給


class ConcreteExample(BaseModel):
    """補完後的具體範例：input/output 是真正能驗證的 dict。"""

    scenario: str
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)


class EnrichedToolSpec(BaseModel):
    """Spec Enricher 補完後的規格 — Code Agent 直接吃這個。

    與 ToolSpec 的差異：
      - examples 變成 ConcreteExample（input/output 是真正的 dict）
      - input_fields / output_fields 是結構化的 FieldSpec list
      - side_effect、tags 已推斷
    """

    name: str
    description: str
    when_to_use: str
    when_not_to_use: str = ""
    examples: list[ConcreteExample] = Field(default_factory=list)
    input_fields: list[FieldSpec] = Field(default_factory=list)
    output_fields: list[FieldSpec] = Field(default_factory=list)
    side_effect: str = "read_only"  # read_only | write_local | write_external
    tags: list[str] = Field(default_factory=list)


# ── Judge wire schema ───────────────────────────────────────────────


class JudgeStepDecision(BaseModel):
    """Judge LLM 對單一 step 的輸出。"""

    step_id: str
    decision: DecisionType
    tool_id: str | None = None        # USE 時填
    compose_chain: list[str] | None = None  # COMPOSE 時填
    gap_spec: ToolSpec | None = None  # GAP 時填
    confidence: float = 0.0
    reasoning: str = ""


class JudgeBatchOutput(BaseModel):
    """Judge LLM 一次 call 處理多個 step 的輸出。"""

    decisions: list[JudgeStepDecision] = Field(default_factory=list)


# ── 內部 domain schema ──────────────────────────────────────────────


class StepDecision(BaseModel):
    """一個 step 經過完整 pipeline 後的最終決策（會持久化到 audit table）。"""

    step: PlannerStep
    decision: DecisionType
    tool_id: str | None = None
    compose_chain: list[str] | None = None
    gap_spec: ToolSpec | None = None

    confidence: float = 0.0
    max_similarity: float = 0.0
    candidates: list[ToolCandidate] = Field(default_factory=list)

    route: DecisionRoute
    reasoning: str = ""
    model_used: str | None = None


class GapDetectionResult(BaseModel):
    """整個 query 的 Phase A 結果。"""

    query_id: str
    query: str
    workspace_id: str
    steps: list[StepDecision] = Field(default_factory=list)

    @property
    def has_gap(self) -> bool:
        return any(s.decision is DecisionType.GAP for s in self.steps)

    @property
    def gap_specs(self) -> list[ToolSpec]:
        return [s.gap_spec for s in self.steps if s.gap_spec is not None]
