"""Test Generator — Phase B 的 [C3]，從 EnrichedToolSpec 生 pytest 測試。

**重要設計（PLAN §22.5.4）**：
這個 module **看不到 code generator 產出的 code**。Tests 從 spec 生，
避免 LLM 在同一 context 同時看到 code + spec 時寫出「遷就 code 而非驗證 spec」的測試。

測試案例三類：
1. 必測：spec.examples 每一個都轉成一個 test case（assertion 對 output）
2. Edge cases：空值、邊界、預期合理輸入但靠近邊界
3. Adversarial：故意給 invalid input，預期拋特定 exception
"""

from __future__ import annotations

import logging
import re

from app.config import settings
from app.providers.base import GenerationRequest, LLMProvider
from app.synthesis.schemas import EnrichedToolSpec

log = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是 pytest 測試產生器。你**看不到實作**，只看到 spec。
你的任務：從 spec 出發，寫出能驗證實作正確性的 pytest 測試集。

測試類型與規則：

1. **happy_path_*（必有）**：spec.examples 每個轉成一個，斷言輸出對應 example.output
2. **edge_*（建議有 1-2 個）**：合法但接近邊界的輸入（例如最小有效值、空字串 fields）
3. **adversarial_***：**只在以下兩種情況才寫，其他情況一律不要寫**：
   a) **Missing required field**：spec.input_fields 內 required=true 且無 default 的欄位
      → 寫 `with pytest.raises(ValidationError): Input()`
   b) **Type mismatch**：傳明顯型別錯誤的值（例如 str 欄位傳 None / dict）
      → 寫 `with pytest.raises(ValidationError): Input(field=<wrong_type>)`

   **特別禁止**（這些是常見錯誤）：
   - 對 `int` 欄位傳負數預期 raise → 負數是合法 int，不會 raise
   - 對 `str` 欄位傳空字串預期 raise → 空字串是合法 str，不會 raise
   - 對任何沒 `Field(gt=, lt=, min_length=...)` 約束的欄位「猜」會 raise

   原則：spec 沒明確說會拒絕的值，就**不要寫測試斷言它會被拒絕**。

撰寫約束：
- 假設 tool class 名稱用 PascalCase 加 "Tool" 結尾（例如 spec.name="get_customer_orders" → "GetCustomerOrdersTool"）
- 假設 input/output 模型用 PascalCase + "Input"/"Output" 結尾
- 用 `import importlib; module = importlib.import_module("generated_tool")` 載入 SUT
  （sandbox 會把 code 寫成 generated_tool.py 模組）
- 每個 test 用 pytest.mark.asyncio
- 用一個共用 fixture 取得 ctx：`from app.schemas.agent import AgentContext`

輸出 plain Python，**不要包 markdown 圍欄**，**不要解釋**。

範例骨架：
```
from __future__ import annotations

import importlib
import pytest
from pydantic import ValidationError

from app.schemas.agent import AgentContext

sut = importlib.import_module("generated_tool")
Tool = sut.GetCustomerOrdersTool
Input = sut.GetCustomerOrdersInput


@pytest.fixture
def ctx() -> AgentContext:
    return AgentContext(workspace_id="test", room_id="r", trace_id="t")


@pytest.mark.asyncio
async def test_happy_path_basic(ctx):
    tool = Tool()
    out = await tool.call(ctx, Input(customer_id="C-123", days=30))
    assert out.total == 1
    assert len(out.orders) == 1


@pytest.mark.asyncio
async def test_edge_days_one(ctx):
    tool = Tool()
    out = await tool.call(ctx, Input(customer_id="C-1", days=1))
    assert out.total >= 0


@pytest.mark.asyncio
async def test_adversarial_missing_required():
    with pytest.raises(ValidationError):
        Input()
```
"""


_CODE_FENCE_RE = re.compile(r"^```(?:python)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def strip_code_fence(text: str) -> str:
    return _CODE_FENCE_RE.sub("", text or "").strip()


def _spec_to_user_prompt(spec: EnrichedToolSpec) -> str:
    """注意這裡刻意不傳遞任何 code，只給 spec，維持 code-test 隔離。"""
    parts = [
        f"id: {spec.name}",
        f"description: {spec.description}",
        f"when_to_use: {spec.when_to_use}",
        f"when_not_to_use: {spec.when_not_to_use}",
        f"side_effect: {spec.side_effect}",
        "",
        "input_fields:",
    ]
    for f in spec.input_fields:
        parts.append(
            f"  - {f.name}: {f.type}"
            f"{' (required)' if f.required else f' (default={f.default!r})'}"
            f" — {f.description}"
        )
    parts.append("output_fields:")
    for f in spec.output_fields:
        parts.append(f"  - {f.name}: {f.type} — {f.description}")
    parts.append("examples (必測 → happy_path):")
    for ex in spec.examples:
        parts.append(f"  - scenario: {ex.scenario}")
        parts.append(f"    input: {ex.input}")
        parts.append(f"    output: {ex.output}")
    return "\n".join(parts)


class TestGenerator:
    # pytest 看到 "Test*" class 會以為是測試類；明確標記跳過收集
    __test__ = False

    def __init__(self, provider: LLMProvider, model: str | None = None) -> None:
        self.provider = provider
        self.model = model or settings.gap_planner_model  # 70B

    async def generate(self, spec: EnrichedToolSpec) -> str:
        req = GenerationRequest(
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": "從以下 spec 產生完整 pytest 測試集：\n\n" + _spec_to_user_prompt(spec),
                }
            ],
            temperature=0.2,
            max_tokens=2048,
            model=self.model,
        )
        resp = await self.provider.generate(req)
        code = strip_code_fence(resp.text)
        if not code:
            log.warning("TestGenerator 收到空 response")
        return code
