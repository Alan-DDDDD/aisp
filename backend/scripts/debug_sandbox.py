"""Debug helper — 從 DB 撈某個 synthesis task 的 code/tests，重跑 LocalSubprocessRunner
並印出完整 stdout/stderr，方便找出為什麼 sandbox 跑出 0 passed 0 failed。

用法：
    .venv/Scripts/python -m scripts.debug_sandbox syn-1f3f7fff94
"""

from __future__ import annotations

import asyncio
import sys

from app.config import settings
from app.db.database import SessionLocal
from app.db.models import ToolSynthesisTask
from app.synthesis.sandbox.local import LocalSubprocessRunner


async def main(task_id: str) -> None:
    async with SessionLocal() as session:
        task = await session.get(ToolSynthesisTask, task_id)
    if task is None:
        print(f"task {task_id} not found")
        return
    if not task.code or not task.tests:
        print(f"task {task_id} has no code or tests")
        return

    print(f"=== Task {task_id} ===")
    print(f"state: {task.state}")
    print(f"attempts: {task.attempts}")
    print(f"workspace: {task.workspace_id}")
    print(f"code length: {len(task.code)} chars")
    print(f"tests length: {len(task.tests)} chars")
    print()

    runner = LocalSubprocessRunner()
    result = await runner.run_python(
        task.code, task.tests, timeout_s=settings.synth_sandbox_timeout_s
    )

    print("=== Sandbox result ===")
    print(f"exit_code: {result.exit_code}")
    print(f"timed_out: {result.timed_out}")
    print(f"setup_error: {result.setup_error}")
    print(f"passed={result.passed} failed={result.failed} errors={result.errors}")
    print(f"failure_messages: {result.failure_messages}")
    print()
    print("=== STDOUT (last 4 KB) ===")
    print(result.stdout)
    print()
    print("=== STDERR (last 4 KB) ===")
    print(result.stderr)
    print()
    print("=== Observations ===")
    for o in result.observations[:30]:
        print(o)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: debug_sandbox.py <task_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
