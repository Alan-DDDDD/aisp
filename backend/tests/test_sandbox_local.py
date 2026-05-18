"""Phase 6 M5 — LocalSubprocessRunner 端到端煙霧測試。

只跑兩個 case（pass / fail），確認：
  - subprocess 真的能起 pytest
  - SandboxResult.passed / failed 對得上
  - observer log 不會 crash 整個流程

注意：這些測試會 spawn 真正的 Python subprocess，比其他 unit test 慢一點。
"""

from __future__ import annotations

import pytest

from app.synthesis.sandbox.local import LocalSubprocessRunner

# pytest.mark.slow 慣例：如果以後 CI 想跳過慢 test，可以一鍵
pytestmark = pytest.mark.asyncio


_TRIVIAL_CODE = '''
def add(a, b):
    return a + b
'''

_PASSING_TESTS = '''
import importlib
sut = importlib.import_module("generated_tool")


def test_add_basic():
    assert sut.add(2, 3) == 5
'''

_FAILING_TESTS = '''
import importlib
sut = importlib.import_module("generated_tool")


def test_add_wrong():
    assert sut.add(2, 3) == 999, "intentional fail"
'''


async def test_local_runner_reports_passed():
    runner = LocalSubprocessRunner()
    result = await runner.run_python(_TRIVIAL_CODE, _PASSING_TESTS, timeout_s=30)
    assert result.passed == 1, f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    assert result.failed == 0
    assert result.all_passed


async def test_local_runner_reports_failed():
    runner = LocalSubprocessRunner()
    result = await runner.run_python(_TRIVIAL_CODE, _FAILING_TESTS, timeout_s=30)
    assert result.failed == 1
    assert result.exit_code != 0
    assert not result.all_passed
    # feedback 要包含失敗訊息給 LLM 修
    fb = result.feedback_for_llm()
    assert "failed" in fb.lower() or "fail" in fb.lower()


async def test_local_runner_handles_syntax_error():
    """code 本身有語法錯 → pytest 起得來但 collection 失敗。"""
    runner = LocalSubprocessRunner()
    result = await runner.run_python("def bad(:", _PASSING_TESTS, timeout_s=20)
    assert not result.all_passed
