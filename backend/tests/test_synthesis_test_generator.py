"""Phase 6 M4 — Test Generator 行為。"""

from __future__ import annotations

from app.synthesis.schemas import ConcreteExample, EnrichedToolSpec, FieldSpec
from app.synthesis.test_generator import TestGenerator
from tests._fakes import ScriptedProvider


def _spec() -> EnrichedToolSpec:
    return EnrichedToolSpec(
        name="echo_tool",
        description="Echo input",
        when_to_use="for echo tests",
        examples=[ConcreteExample(scenario="echo hi", input={"msg": "hi"}, output={"echoed": "hi"})],
        input_fields=[FieldSpec(name="msg", type="str", description="")],
        output_fields=[FieldSpec(name="echoed", type="str", description="")],
    )


async def test_test_generator_returns_text():
    expected = "import pytest\n\nasync def test_happy(): pass\n"
    provider = ScriptedProvider([expected])
    tg = TestGenerator(provider=provider)
    out = await tg.generate(_spec())
    # strip_code_fence 砍尾巴空白，normalize 比對
    assert out.strip() == expected.strip()


async def test_test_generator_does_not_see_code():
    """code-test 隔離（PLAN §22.5.4）：test generator 的 user prompt 不該出現 code 內容。"""
    provider = ScriptedProvider([""])
    tg = TestGenerator(provider=provider)
    await tg.generate(_spec())
    user_content = provider.calls[0].messages[0]["content"]
    # 確認沒有意外把 BaseTool subclass 的 code 帶進來
    assert "class " not in user_content or "BaseTool" not in user_content
    # 但 spec 內容該在
    assert "echo_tool" in user_content
    assert "scenario: echo hi" in user_content


async def test_test_generator_strips_fence():
    provider = ScriptedProvider(["```python\nimport pytest\n```"])
    tg = TestGenerator(provider=provider)
    out = await tg.generate(_spec())
    assert "```" not in out
    assert out == "import pytest"
