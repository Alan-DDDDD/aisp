"""Phase 6 M5 — SynthesisOrchestrator state machine（mock runner）。

驗證：
  - happy path：一次過
  - 第一次 static check fail，第二次 ok → 通過
  - 第一次 sandbox fail，第二次 ok → 通過
  - max_attempts 用盡 → success=False，error 訊息
  - feedback 真的被餵回 code_gen
"""

from __future__ import annotations

from app.synthesis.orchestrator import SynthesisOrchestrator
from app.synthesis.sandbox.base import SandboxResult, SandboxRunner
from app.synthesis.schemas import ToolSpec

_VALID_CODE = '''
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

_INVALID_CODE_BAD_IMPORT = "import subprocess\n\nclass X: pass\n"


_ENRICHED_JSON = """
{
  "name": "echo_tool",
  "description": "Echo input",
  "when_to_use": "for echo",
  "when_not_to_use": "not prod",
  "examples": [{"scenario": "x", "input": {"msg": "hi"}, "output": {"echoed": "hi"}}],
  "input_fields": [{"name": "msg", "type": "str", "description": "msg"}],
  "output_fields": [{"name": "echoed", "type": "str", "description": "out"}],
  "side_effect": "read_only",
  "tags": ["echo"]
}
"""


class MockRunner(SandboxRunner):
    """逐次回傳預設 SandboxResult。"""

    name = "mock"

    def __init__(self, results: list[SandboxResult]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, str]] = []

    async def run_python(  # type: ignore[override]
        self, code: str, tests: str, *, timeout_s: int = 60
    ) -> SandboxResult:
        self.calls.append((code, tests))
        if self._results:
            return self._results.pop(0)
        return SandboxResult(exit_code=-1, setup_error="MockRunner: out of scripted results")


def _ok_result() -> SandboxResult:
    return SandboxResult(exit_code=0, passed=3, failed=0)


def _fail_result(msg: str = "test_x failed") -> SandboxResult:
    return SandboxResult(
        exit_code=1, passed=1, failed=1, failure_messages=[msg], stderr=msg
    )


def _spec() -> ToolSpec:
    return ToolSpec(name="echo_tool", description="Echo", when_to_use="x")


async def test_happy_path_first_attempt(monkeypatch):
    """一次過：enricher → test_gen → code_gen → static OK → sandbox OK"""
    from tests._fakes import ScriptedProvider

    provider = ScriptedProvider([
        _ENRICHED_JSON,        # enricher
        "def test_x(): pass",  # test_gen
        _VALID_CODE,           # code_gen attempt 1
    ])
    runner = MockRunner([_ok_result()])
    orch = SynthesisOrchestrator(provider=provider, runner=runner)

    result = await orch.synthesize(_spec())

    assert result.success
    assert result.attempt_count == 1
    assert len(runner.calls) == 1
    # code_generator 會 strip leading/trailing whitespace；比對前 normalize
    assert result.final_code == _VALID_CODE.strip()


async def test_recovers_after_static_check_failure():
    """第一次 code 有 subprocess import → static reject；第二次 OK → 通過。"""
    from tests._fakes import ScriptedProvider

    provider = ScriptedProvider([
        _ENRICHED_JSON,
        "def test_x(): pass",
        _INVALID_CODE_BAD_IMPORT,   # attempt 1 — static fail
        _VALID_CODE,                # attempt 2 — ok
    ])
    runner = MockRunner([_ok_result()])
    orch = SynthesisOrchestrator(provider=provider, runner=runner)

    result = await orch.synthesize(_spec())

    assert result.success
    assert result.attempt_count == 2
    assert result.attempts[0].static_ok is False
    assert result.attempts[1].static_ok is True
    # static fail 的那輪不該叫到 sandbox
    assert len(runner.calls) == 1


async def test_recovers_after_sandbox_failure():
    """第一次 sandbox 紅；第二次綠 → 通過。Feedback 應被帶回 LLM。"""
    from tests._fakes import ScriptedProvider

    provider = ScriptedProvider([
        _ENRICHED_JSON,
        "def test_x(): pass",
        _VALID_CODE,  # attempt 1
        _VALID_CODE,  # attempt 2
    ])
    runner = MockRunner([_fail_result("test_x failed"), _ok_result()])
    orch = SynthesisOrchestrator(provider=provider, runner=runner)

    result = await orch.synthesize(_spec())

    assert result.success
    assert result.attempt_count == 2
    # 第二次 code_gen 的 feedback 應包含上一輪的失敗訊息
    assert "test_x failed" in result.attempts[1].feedback_used


async def test_exhausts_attempts_returns_failure():
    """所有 attempts 都 sandbox 紅 → success=False，error 標明需要 rescue。"""
    from tests._fakes import ScriptedProvider

    provider = ScriptedProvider([
        _ENRICHED_JSON,
        "def test_x(): pass",
        _VALID_CODE,
        _VALID_CODE,
        _VALID_CODE,
    ])
    runner = MockRunner([_fail_result(), _fail_result(), _fail_result()])
    orch = SynthesisOrchestrator(provider=provider, runner=runner, max_attempts=3)

    result = await orch.synthesize(_spec())

    assert not result.success
    assert result.attempt_count == 3
    assert result.error is not None and "rescue" in result.error
    assert result.sandbox_result is not None


async def test_behavior_summary_aggregates_observations():
    """behavior_summary 把 observations 依 type 計數，給 M6 審核 UI 顯示。"""
    from tests._fakes import ScriptedProvider

    sandbox = SandboxResult(
        exit_code=0,
        passed=2,
        observations=[
            {"type": "socket", "args": "(AF_INET,)"},
            {"type": "socket", "args": "(AF_INET6,)"},
            {"type": "open", "path": "/tmp/x"},
        ],
    )
    provider = ScriptedProvider([_ENRICHED_JSON, "def test_x(): pass", _VALID_CODE])
    runner = MockRunner([sandbox])
    orch = SynthesisOrchestrator(provider=provider, runner=runner)

    result = await orch.synthesize(_spec())

    assert result.success
    summary = result.behavior_summary
    assert summary["observations_by_type"] == {"socket": 2, "open": 1}
    assert summary["passed"] == 2
