"""Phase 6 M4 — AST 靜態檢查的 pass/fail 邊界。

每個 test 都針對一個「LLM 可能犯的錯」，確認 check 真的擋得下來。
"""

from __future__ import annotations

from app.synthesis.static_check import check

_GOOD_CODE = '''
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.agent import AgentContext
from app.tools.base import BaseTool, SideEffect, ToolExample


class EchoInput(BaseModel):
    msg: str


class EchoOutput(BaseModel):
    echoed: str


class EchoTool(BaseTool):
    id = "echo_tool"
    version = "1.0.0"
    source = "generated"

    description = "Echo input."
    when_to_use = "for testing echo"
    when_NOT_to_use = "do not use in prod"
    examples = [ToolExample(scenario="x", input={"msg": "hi"}, output={"echoed": "hi"})]
    input_schema = EchoInput
    output_schema = EchoOutput
    side_effect = SideEffect.READ_ONLY
    requires_approval = False
    tags = ["echo"]

    async def call(self, ctx: AgentContext, payload: EchoInput) -> EchoOutput:
        return EchoOutput(echoed=payload.msg)
'''


def test_good_code_passes():
    r = check(_GOOD_CODE)
    assert r.ok, r.errors


def test_empty_fails():
    r = check("")
    assert not r.ok
    assert "code 為空" in r.errors[0]


def test_syntax_error_fails():
    r = check("def x(:")
    assert not r.ok
    assert "SyntaxError" in r.errors[0]


def test_forbidden_subprocess_import_fails():
    code = _GOOD_CODE.replace(
        "from __future__ import annotations",
        "from __future__ import annotations\nimport subprocess",
    )
    r = check(code)
    assert not r.ok
    assert any("subprocess" in e for e in r.errors)


def test_forbidden_httpx_import_fails():
    code = _GOOD_CODE.replace(
        "from __future__ import annotations",
        "from __future__ import annotations\nimport httpx",
    )
    r = check(code)
    assert not r.ok
    assert any("httpx" in e for e in r.errors)


def test_forbidden_os_import_fails():
    code = _GOOD_CODE.replace(
        "from __future__ import annotations",
        "from __future__ import annotations\nimport os",
    )
    r = check(code)
    assert not r.ok


def test_forbidden_app_db_import_fails():
    code = _GOOD_CODE.replace(
        "from app.tools.base import BaseTool, SideEffect, ToolExample",
        "from app.db.database import SessionLocal\nfrom app.tools.base import BaseTool, SideEffect, ToolExample",
    )
    r = check(code)
    assert not r.ok


def test_eval_call_fails():
    code = _GOOD_CODE.replace(
        "return EchoOutput(echoed=payload.msg)",
        'return EchoOutput(echoed=eval(payload.msg))',
    )
    r = check(code)
    assert not r.ok
    assert any("eval" in e for e in r.errors)


def test_open_call_fails():
    code = _GOOD_CODE.replace(
        "return EchoOutput(echoed=payload.msg)",
        'open("foo.txt", "w")\n        return EchoOutput(echoed=payload.msg)',
    )
    r = check(code)
    assert not r.ok
    assert any("open" in e for e in r.errors)


def test_missing_class_fails():
    code = "x = 1\n"
    r = check(code)
    assert not r.ok
    assert any("BaseTool subclass" in e for e in r.errors)


def test_two_basetools_fails():
    code = _GOOD_CODE + "\n\nclass SecondTool(BaseTool):\n    id = 'x'\n"
    r = check(code)
    assert not r.ok
    assert any("找到 2 個" in e for e in r.errors)


def test_missing_call_method_fails():
    code = _GOOD_CODE.replace(
        "    async def call(self, ctx: AgentContext, payload: EchoInput) -> EchoOutput:\n"
        "        return EchoOutput(echoed=payload.msg)\n",
        "    pass\n",
    )
    r = check(code)
    assert not r.ok
    assert any("async def call" in e for e in r.errors)


def test_sync_call_method_fails():
    code = _GOOD_CODE.replace("async def call", "def call")
    r = check(code)
    assert not r.ok
    assert any("async def" in e for e in r.errors)


def test_missing_when_not_to_use_fails():
    code = _GOOD_CODE.replace(
        '    when_NOT_to_use = "do not use in prod"\n',
        "",
    )
    r = check(code)
    assert not r.ok
    assert any("when_NOT_to_use" in e for e in r.errors)


def test_dynamic_getattr_warns_but_passes():
    """動態 getattr 可能被用來繞白名單；先警告不擋（PLAN：先 audit 再 enforce）。"""
    code = _GOOD_CODE.replace(
        "return EchoOutput(echoed=payload.msg)",
        'name = "msg"\n        return EchoOutput(echoed=getattr(payload, name))',
    )
    r = check(code)
    assert r.ok
    assert any("getattr" in w for w in r.warnings)


def test_feedback_for_llm_includes_errors():
    """失敗訊息要組成 LLM 能讀的 feedback。"""
    r = check("import subprocess\n")
    assert not r.ok
    fb = r.feedback_for_llm()
    assert "subprocess" in fb
    assert "靜態檢查失敗" in fb
