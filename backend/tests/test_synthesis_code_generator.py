"""Phase 6 M4 — Code Generator 行為。"""

from __future__ import annotations

from app.synthesis.code_generator import CodeGenerator, strip_code_fence
from app.synthesis.schemas import ConcreteExample, EnrichedToolSpec, FieldSpec
from tests._fakes import ScriptedProvider


def _make_spec() -> EnrichedToolSpec:
    return EnrichedToolSpec(
        name="echo_tool",
        description="Echo input",
        when_to_use="for echo tests",
        when_not_to_use="not for prod",
        examples=[ConcreteExample(scenario="echo hi", input={"msg": "hi"}, output={"echoed": "hi"})],
        input_fields=[FieldSpec(name="msg", type="str", description="輸入訊息")],
        output_fields=[FieldSpec(name="echoed", type="str", description="echo 回")],
        side_effect="read_only",
        tags=["echo"],
    )


async def test_code_generator_returns_response_text():
    response_code = "class EchoTool(BaseTool):\n    id = 'echo_tool'\n"
    provider = ScriptedProvider([response_code])
    cg = CodeGenerator(provider=provider)
    out = await cg.generate(_make_spec())
    # strip_code_fence 會把末尾 whitespace 砍掉，比對時 normalize
    assert out.strip() == response_code.strip()


async def test_code_generator_strips_markdown_fence():
    """LLM 常加 ```python ... ``` 圍欄，需要剝掉。"""
    fenced = "```python\nclass X(BaseTool):\n    pass\n```"
    provider = ScriptedProvider([fenced])
    cg = CodeGenerator(provider=provider)
    out = await cg.generate(_make_spec())
    assert "```" not in out
    assert out.startswith("class X(BaseTool)")


async def test_code_generator_passes_feedback_back_to_llm():
    """失敗修正迴圈：feedback 要被帶進 user prompt。"""
    provider = ScriptedProvider(["class X(BaseTool):\n    pass\n"])
    cg = CodeGenerator(provider=provider)
    await cg.generate(_make_spec(), feedback="忘了 async def call")
    user_content = provider.calls[0].messages[0]["content"]
    assert "忘了 async def call" in user_content


def test_strip_code_fence_handles_plain_text():
    assert strip_code_fence("class X: pass") == "class X: pass"
    assert strip_code_fence("") == ""
    assert strip_code_fence(None) == ""  # type: ignore[arg-type]
