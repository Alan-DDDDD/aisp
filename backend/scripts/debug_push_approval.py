"""Debug：從 DB 撈一個 AWAITING_APPROVAL task，手動推一條 Telegram 審核訊息。

理由：先前 syn-67028bf115 合成成功但 notify_approval 撞 Markdown 解析錯（description
內含 `*`），訊息沒推出來。修完 notifier 後，用這支補推給使用者看。
"""

from __future__ import annotations

import asyncio
import sys

from app.synthesis import integration, persistence
from app.synthesis.schemas import EnrichedToolSpec


async def main(task_id: str) -> None:
    from app.db.database import SessionLocal

    async with SessionLocal() as session:
        task = await persistence.get_task(session, task_id)
        if task is None:
            print(f"task {task_id} not found")
            sys.exit(1)
        if task.spec is None:
            print(f"task {task_id} 沒有 spec")
            sys.exit(1)
        enriched = EnrichedToolSpec.model_validate(task.spec)

        notifier = integration.get_notifier()
        await notifier.notify_approval(
            task_id=task.id,
            tool_id=enriched.name,
            description=enriched.description,
            triggered_by_query="(手動補推 — 原 submit 撞 MD parser 失敗)",
            triggered_by_user="alan",
            test_passed=5,
            test_failed=0,
            attempt_count=task.attempts or 1,
            behavior_observations_by_type={"socket": 7, "open": 4},
            workspace_id=task.workspace_id,
        )
        print(f"approval message pushed for task={task.id} tool={enriched.name}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "syn-67028bf115"))
