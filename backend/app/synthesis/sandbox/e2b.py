"""E2BRunner — 用 E2B Cloud Sandbox 跑 generated tool 的 test。

設定（PROD 走這條）：
  1. 註冊 E2B 帳號：https://e2b.dev
  2. `pip install e2b-code-interpreter`
  3. `export E2B_API_KEY=...`（或寫進 .env）

E2B 提供真正的 Linux container 隔離。免費 tier 給 100 hours / 月，side project demo
用量遠低於此。

如果沒裝 SDK 或沒設 key，這個 class 不會在 import 時爆，而是在實際 run 時才丟
清楚的訊息引導使用者設定。
"""

from __future__ import annotations

import contextlib
import json
import logging
from pathlib import Path

from app.synthesis.sandbox.base import SandboxResult, SandboxRunner
from app.synthesis.sandbox.local import (
    CONFTEST_SOURCE,
    _parse_pytest_summary,
)
from app.synthesis.sandbox.observer import OBSERVER_SOURCE

log = logging.getLogger(__name__)


_E2B_INSTALL_HINT = (
    "E2B sandbox 需要：\n"
    "  1. pip install e2b-code-interpreter\n"
    "  2. 環境變數 E2B_API_KEY（在 https://e2b.dev/dashboard/keys 取得）\n"
    "或回退到 LocalSubprocessRunner（dev 用）。"
)


class E2BRunner(SandboxRunner):
    """雲端 sandbox 實作。SDK / API key 必須齊備。"""

    name = "e2b"

    def __init__(self, template: str | None = None, api_key: str | None = None) -> None:
        # template = E2B sandbox template id；None 用預設 python image
        self.template = template
        self.api_key = api_key  # None 時 SDK 自動讀 E2B_API_KEY env

    async def run_python(
        self,
        code: str,
        tests: str,
        *,
        timeout_s: int = 60,
    ) -> SandboxResult:
        try:
            from e2b_code_interpreter import AsyncSandbox  # type: ignore
        except ImportError as e:
            return SandboxResult(
                exit_code=-2,
                setup_error=f"e2b SDK 未安裝：{e}\n{_E2B_INSTALL_HINT}",
            )

        try:
            sbx = await AsyncSandbox.create(
                template=self.template,
                api_key=self.api_key,
                timeout=timeout_s + 30,  # SDK timeout 比 pytest timeout 寬一點
            )
        except Exception as e:  # noqa: BLE001
            return SandboxResult(
                exit_code=-2,
                setup_error=f"E2B sandbox 啟動失敗：{e}\n{_E2B_INSTALL_HINT}",
            )

        try:
            # 寫入工作檔
            workdir = "/home/user/aisp"
            await sbx.commands.run(f"mkdir -p {workdir}")
            await sbx.files.write(f"{workdir}/generated_tool.py", code)
            await sbx.files.write(f"{workdir}/test_generated_tool.py", tests)
            await sbx.files.write(f"{workdir}/observer.py", OBSERVER_SOURCE)
            await sbx.files.write(f"{workdir}/conftest.py", CONFTEST_SOURCE)

            # 把 backend 的 app/ 模組打包進去，讓 generated code 能 import
            await _upload_app_modules(sbx, workdir)

            # 執行 pytest
            obs_path = f"{workdir}/observer_log.json"
            env = {
                "OBSERVER_LOG": obs_path,
                "PYTHONIOENCODING": "utf-8",
                "PYTHONPATH": workdir,
            }
            cmd = (
                "cd "
                + workdir
                + " && python -m pytest -q --no-header test_generated_tool.py"
            )
            run = await sbx.commands.run(cmd, envs=env, timeout=timeout_s)

            stdout = (run.stdout or "")
            stderr = (run.stderr or "")
            passed, failed, errors, skipped = _parse_pytest_summary(stdout)

            # 撈 observer log
            observations: list[dict] = []
            try:
                content = await sbx.files.read(obs_path)
                observations = json.loads(content)
                if not isinstance(observations, list):
                    observations = []
            except Exception:  # noqa: BLE001
                observations = []

            from re import findall

            failure_messages = findall(r"^FAILED\s+(.+)$", stdout, flags=8)  # re.MULTILINE

            return SandboxResult(
                exit_code=run.exit_code or 0,
                passed=passed,
                failed=failed,
                errors=errors,
                skipped=skipped,
                stdout=stdout[-4000:],
                stderr=stderr[-4000:],
                failure_messages=failure_messages,
                observations=observations,
            )
        except Exception as e:  # noqa: BLE001
            log.exception("E2BRunner 執行階段失敗")
            return SandboxResult(exit_code=-2, setup_error=f"E2B 執行失敗：{e}")
        finally:
            with contextlib.suppress(Exception):
                await sbx.kill()


async def _upload_app_modules(sbx, workdir: str) -> None:
    """把 generated code 會 import 的最小 app/ 子集打包上 sandbox。

    白名單只包：app/tools/base.py, app/schemas/agent.py（與這兩個依賴的最小路徑）。
    不要整包 app/ 丟上去 —— 會把 app.db / app.providers 等敏感模組也帶過去。
    """
    backend_root = Path(__file__).resolve().parents[3]
    files = [
        "app/__init__.py",
        "app/tools/__init__.py",
        "app/tools/base.py",
        "app/schemas/__init__.py",
        "app/schemas/agent.py",
    ]
    for rel in files:
        local = backend_root / rel
        if local.exists():
            content = local.read_text(encoding="utf-8")
            await sbx.files.write(f"{workdir}/{rel}", content)
