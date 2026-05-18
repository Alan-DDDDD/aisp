"""Code Generator — Phase B 的 [C2]，把 EnrichedToolSpec 變成 Python code。

設計要點（PLAN §22.5.2）：
- 嚴格 contract：subclass BaseTool、async def call、用 input_schema / output_schema
- White list imports，禁 exec/eval/subprocess/socket（M4 的 AST check 會強制）
- Few-shot：把 KBSearchTool 簡化版當範例給 LLM 模仿
- LLM 直接回 plain Python source，不包 JSON
"""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.providers.base import GenerationRequest, LLMProvider
from app.synthesis.schemas import EnrichedToolSpec

log = logging.getLogger(__name__)


# 範例 tool（少樣本）；刻意去掉 DB 操作，讓 LLM 不會學去碰 DB
FEW_SHOT_EXAMPLE = '''\
"""Example: compute_loan_payment — 計算每月分期金額。"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.agent import AgentContext
from app.tools.base import BaseTool, SideEffect, ToolExample


class ComputeLoanPaymentInput(BaseModel):
    principal: float
    annual_rate: float
    months: int


class ComputeLoanPaymentOutput(BaseModel):
    monthly_payment: float
    total_interest: float


class ComputeLoanPaymentTool(BaseTool):
    id = "compute_loan_payment"
    version = "1.0.0"
    source = "generated"

    description = "Compute monthly payment for a fixed-rate loan."
    when_to_use = "計算等額本息分期方案的月付金與總利息"
    when_NOT_to_use = "不要用於變動利率方案；不要用於本金結算"
    examples = [
        ToolExample(
            scenario="本金 100 萬、年利率 3%、24 期",
            input={"principal": 1_000_000.0, "annual_rate": 0.03, "months": 24},
            output={"monthly_payment": 42984.45, "total_interest": 31626.80},
        ),
    ]

    input_schema = ComputeLoanPaymentInput
    output_schema = ComputeLoanPaymentOutput

    side_effect = SideEffect.READ_ONLY
    requires_approval = False
    tags = ["loan", "finance"]

    async def call(  # type: ignore[override]
        self, ctx: AgentContext, payload: ComputeLoanPaymentInput
    ) -> ComputeLoanPaymentOutput:
        r = payload.annual_rate / 12.0
        n = payload.months
        if r == 0:
            m = payload.principal / n
        else:
            m = payload.principal * r * (1 + r) ** n / ((1 + r) ** n - 1)
        total_interest = m * n - payload.principal
        return ComputeLoanPaymentOutput(
            monthly_payment=round(m, 2),
            total_interest=round(total_interest, 2),
        )
'''


SYSTEM_PROMPT = """你是 BaseTool subclass 的 code generator。輸出單一 .py 檔的完整原始碼。

嚴格 contract（不可違反，違反會被 AST check 擋下來）：
1. 必須 subclass BaseTool（from app.tools.base import BaseTool, SideEffect, ToolExample）
2. 必須實作 async def call(self, ctx: AgentContext, payload) -> output_schema 實例
3. 必須定義 input_schema / output_schema（都是 BaseModel subclass）
4. 必須設定：id / version="1.0.0" / source="generated" / description / when_to_use / when_NOT_to_use
   / examples (list[ToolExample]) / side_effect / tags
5. requires_approval：side_effect=write_external 時設 True，其他 False
6. 只能 import：__future__, pydantic, app.schemas.agent, app.tools.base, datetime, decimal, math,
   json, re, typing, enum, collections, itertools, functools
7. 禁止使用：exec / eval / __import__ / compile / globals / subprocess / socket / requests / httpx
   / urllib / sqlalchemy / open() / Path.open() / os.system / os.popen
8. 不要寫 main / 不要寫 print / 不要寫 if __name__ 區塊

輸出 plain Python，**不要包 markdown 圍欄**，**不要解釋**。範例（看完模仿風格）：

""" + FEW_SHOT_EXAMPLE


_CODE_FENCE_RE = re.compile(r"^```(?:python)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def strip_code_fence(text: str) -> str:
    """LLM 常忍不住加 ```python ... ``` 圍欄。"""
    return _CODE_FENCE_RE.sub("", text or "").strip()


def _format_spec_for_codegen(spec: EnrichedToolSpec) -> str:
    """把 enriched spec 序列化成 LLM 易讀的形式。"""
    lines = [
        f"id: {spec.name}",
        f"description: {spec.description}",
        f"when_to_use: {spec.when_to_use}",
        f"when_NOT_to_use: {spec.when_not_to_use}",
        f"side_effect: {spec.side_effect}",
        f"tags: {spec.tags}",
        "",
        "input_fields:",
    ]
    for f in spec.input_fields:
        lines.append(
            f"  - {f.name}: {f.type}"
            f"{' (required)' if f.required else f' (default={f.default!r})'}"
            f" — {f.description}"
        )
    lines.append("output_fields:")
    for f in spec.output_fields:
        lines.append(f"  - {f.name}: {f.type} — {f.description}")
    lines.append("examples:")
    for ex in spec.examples:
        lines.append(f"  - {ex.scenario}")
        lines.append(f"    input: {ex.input}")
        lines.append(f"    output: {ex.output}")
    return "\n".join(lines)


class CodeGenerator:
    def __init__(self, provider: LLMProvider, model: str | None = None) -> None:
        self.provider = provider
        self.model = model or settings.gap_planner_model  # 70B

    async def generate(
        self,
        spec: EnrichedToolSpec,
        feedback: str | None = None,
    ) -> str:
        """產出 BaseTool subclass 的 .py 原始碼。

        feedback：M5 失敗修正迴圈用，把上一輪錯誤訊息餵回 LLM。
        """
        user_parts = ["請依此 spec 寫出 BaseTool subclass：\n\n", _format_spec_for_codegen(spec)]
        if feedback:
            user_parts.append("\n\n上一次嘗試的失敗訊息（請修正再生）：\n" + feedback)

        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "".join(user_parts)}],
            temperature=0.2,
            max_tokens=2048,
            model=self.model,
        )
        resp = await self.provider.generate(req)
        code = strip_code_fence(resp.text)
        if not code:
            log.warning("CodeGenerator 收到空 response")
        return code
