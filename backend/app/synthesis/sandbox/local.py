"""LocalSubprocessRunner — dev 用 fallback，不是真正的 sandbox。

警告：這個實作**沒有真正隔離**：subprocess 仍能存取 host 檔案系統與網路。
存在的價值只有兩個：
  1. 沒 E2B 帳號時讓本機開發能跑通 pipeline
  2. CI / 單機 demo 時不需外部服務

正式使用一定要切到 E2BRunner（PLAN §22.5.3）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path

from app.synthesis.sandbox.base import SandboxResult, SandboxRunner
from app.synthesis.sandbox.observer import OBSERVER_SOURCE

log = logging.getLogger(__name__)


# pytest summary 在 -q 與 verbose 模式格式略異：
#   verbose: "========== 1 passed, 1 failed in 0.12s =========="
#   -q     : "1 passed in 0.01s"
# 策略：找最後一條同時含 "in X.XXs" 與計數的 line，再從該 line 抽各類計數。
_TIME_LINE_RE = re.compile(r"in\s+[\d.]+\s*s", re.IGNORECASE)
_COUNT_RE = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped)", re.IGNORECASE)

# 抓單一 test 失敗的標題：「FAILED tests/test_x.py::test_y - ...」
_FAILED_LINE_RE = re.compile(r"^FAILED\s+(.+)$", re.MULTILINE)


CONFTEST_SOURCE = r"""# auto-generated: 讓 sandbox dir 進 sys.path，並啟動行為觀察 shim
import sys
import pathlib

_HERE = pathlib.Path(__file__).parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

# 啟動 observer（import 即執行 module-level monkey-patch）
import observer  # noqa: F401, E402
"""


class LocalSubprocessRunner(SandboxRunner):
    name = "local-subprocess"

    async def run_python(
        self,
        code: str,
        tests: str,
        *,
        timeout_s: int = 60,
    ) -> SandboxResult:
        with tempfile.TemporaryDirectory(prefix="aisp_sandbox_") as td:
            workdir = Path(td)
            obs_path = workdir / "observer_log.json"

            (workdir / "generated_tool.py").write_text(code, encoding="utf-8")
            (workdir / "test_generated_tool.py").write_text(tests, encoding="utf-8")
            (workdir / "observer.py").write_text(OBSERVER_SOURCE, encoding="utf-8")
            (workdir / "conftest.py").write_text(CONFTEST_SOURCE, encoding="utf-8")

            cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "test_generated_tool.py"]
            # Windows 上完全 override env 會讓 asyncio 載不到 _overlapped（缺 SYSTEMROOT 等）。
            # LocalSubprocessRunner 本來就不是真隔離（dev fallback），整個 os.environ 帶過去
            # 是 acceptable 取捨；要真隔離請用 E2BRunner。
            env = {
                **os.environ,
                "OBSERVER_LOG": str(obs_path),
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": str(_backend_root()),
            }
            # 用 sync subprocess + executor 而非 asyncio.create_subprocess_exec。
            # Windows + uvicorn 預設 SelectorEventLoop → asyncio subprocess 直接 raise
            # NotImplementedError（message 還常常是空的）；走 executor 繞開這個限制。
            loop = asyncio.get_running_loop()
            try:
                proc = await loop.run_in_executor(
                    None,
                    partial(
                        subprocess.run,
                        cmd,
                        cwd=str(workdir),
                        env=env,
                        capture_output=True,
                        timeout=timeout_s,
                    ),
                )
            except subprocess.TimeoutExpired:
                return SandboxResult(
                    exit_code=-1,
                    timed_out=True,
                    stderr=f"timeout after {timeout_s}s",
                )
            except Exception as e:  # noqa: BLE001
                log.warning(
                    "LocalSubprocessRunner failed to spawn pytest: %s: %s",
                    type(e).__name__,
                    e,
                )
                return SandboxResult(
                    exit_code=-2,
                    setup_error=f"{type(e).__name__}: {e}",
                )

            return self._build_result(
                exit_code=proc.returncode or 0,
                stdout=proc.stdout.decode("utf-8", errors="replace"),
                stderr=proc.stderr.decode("utf-8", errors="replace"),
                obs_path=obs_path,
            )

    @staticmethod
    def _build_result(
        exit_code: int, stdout: str, stderr: str, obs_path: Path
    ) -> SandboxResult:
        passed, failed, errors, skipped = _parse_pytest_summary(stdout)
        failure_messages = _FAILED_LINE_RE.findall(stdout)
        observations: list[dict] = []
        if obs_path.exists():
            try:
                observations = json.loads(obs_path.read_text(encoding="utf-8"))
                if not isinstance(observations, list):
                    observations = []
            except (json.JSONDecodeError, OSError):
                observations = []

        return SandboxResult(
            exit_code=exit_code,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            stdout=stdout[-4000:],
            stderr=stderr[-4000:],
            failure_messages=failure_messages,
            observations=observations,
        )


def _parse_pytest_summary(text: str) -> tuple[int, int, int, int]:
    """從 pytest 摘要回 (passed, failed, errors, skipped)。

    支援 -q（無 ====）與 verbose（有 ====）兩種；遇多條摘要時取最後一條
    （避免被 warnings summary 干擾）。
    """
    summary_line: str | None = None
    for line in text.splitlines():
        if _TIME_LINE_RE.search(line) and _COUNT_RE.search(line):
            summary_line = line
    if not summary_line:
        return (0, 0, 0, 0)

    p = f = e = s = 0
    for m in _COUNT_RE.finditer(summary_line):
        n = int(m.group(1))
        kind = m.group(2).lower()
        if kind == "passed":
            p = n
        elif kind == "failed":
            f = n
        elif kind.startswith("error"):
            e = n
        elif kind == "skipped":
            s = n
    return p, f, e, s


def _backend_root() -> Path:
    """從這個 module 位置回推 backend 根目錄。"""
    # this file: backend/app/synthesis/sandbox/local.py
    return Path(__file__).resolve().parents[3]
