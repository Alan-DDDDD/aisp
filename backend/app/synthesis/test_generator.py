"""Test Generator — Phase B 的 [C3]，從 EnrichedToolSpec 生 pytest 測試。

**重要設計（PLAN §22.5.4）**：
這個 module **看不到 code generator 產出的 code**。Tests 從 spec 生，
避免 LLM 在同一 context 同時看到 code + spec 時寫出「遷就 code 而非驗證 spec」的測試。

測試案例兩類（不再生 adversarial）：
1. 必測：spec.examples 每一個都轉成一個 test case（assertion 對 output）
2. Edge cases：合法但接近邊界的輸入（最小有效值、空字串等）

歷史背景：原本還有 adversarial 一類（給 invalid input 預期 raise），
但 LLM 屢屢誤判 Pydantic 的 coercion 行為（例如 str "100" 給 float 欄位會被
自動 coerce 不會 raise）→ 每次都自己寫掛 sandbox。價值（測 Pydantic 自身）
本來就低，移除。
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

只生兩類測試（**任何其他類別一律不寫**）：

1. **happy_path_*（必有）**：spec.examples 每一個轉成一個 test，
   斷言輸出 == example.output 的每個欄位
2. **edge_*（建議 1-2 個）**：合法但接近邊界的輸入
   （最小有效值、零值、空字串作為合法字串等）

**禁止項目**（即使聽起來很合理也別寫）：
- 任何 `with pytest.raises(ValidationError)` / `TypeError` / `ValueError` 的測試
- 任何「驗證 Pydantic 會拒絕某 input」的測試
- 任何 `adversarial_*`、`invalid_*`、`error_*` 命名的測試

原因：Pydantic v2 有 type coercion（"100" → 100.0 不會 raise）；
spec 內沒明文約束的拒絕行為都是猜測，且這類測試的價值在「測 Pydantic 自身」
而不是「測這個工具」，留給上游 schema 驗證即可。

撰寫約束：
- 假設 tool class 名稱用 PascalCase 加 "Tool" 結尾（spec.name="get_customer_orders" → "GetCustomerOrdersTool"）
- 假設 input/output 模型用 PascalCase + "Input"/"Output" 結尾
- 用 `import importlib; module = importlib.import_module("generated_tool")` 載入 SUT
- 每個 async test 用 `@pytest.mark.asyncio`
- 用共用 fixture 取得 ctx：`from app.schemas.agent import AgentContext`

輸出 plain Python，**不要包 markdown 圍欄**，**不要解釋**。

範例骨架：
```
from __future__ import annotations

import importlib
import pytest

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
