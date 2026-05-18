"""Phase 6 M6 — ApprovalService state machine + Telegram 整合（FakeSender）。

驗證：
  - submit() 成功 → 寫 ToolSynthesisTask=AWAITING_APPROVAL + Telegram 訊息
  - submit() 失敗（rescue）→ 寫 AWAITING_HUMAN_RESCUE + rescue 訊息
  - approve() → REGISTERED + GeneratedTool row + 註冊到 tool_registry + 寫檔
  - reject() → DISCARDED + 審核紀錄
  - queue_refine() → 回到 CODE_GENERATING + hint 進審核紀錄
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import models  # noqa: F401 — register tables
from app.db.database import Base
from app.db.models import GeneratedTool, ToolReviewHistory, ToolSynthesisTask
from app.synthesis import persistence
from app.synthesis.approval import ApprovalService
from app.synthesis.orchestrator import SynthesisAttempt, SynthesisResult
from app.synthesis.sandbox.base import SandboxResult
from app.synthesis.schemas import (
    ConcreteExample,
    EnrichedToolSpec,
    FieldSpec,
    ToolSpec,
)
from app.synthesis.tool_retriever import ToolRetriever
from app.telegram.callback_router import ApprovalCallback
from app.telegram.notifier import Notifier
from app.telegram.sender import FakeSender
from app.tools import registry as tool_registry

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
    when_to_use = "for testing"
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


def _make_success_result() -> SynthesisResult:
    enriched = EnrichedToolSpec(
        name="echo_tool",
        description="Echo input",
        when_to_use="for testing",
        when_not_to_use="not prod",
        examples=[ConcreteExample(scenario="x", input={"msg": "hi"}, output={"echoed": "hi"})],
        input_fields=[FieldSpec(name="msg", type="str", description="")],
        output_fields=[FieldSpec(name="echoed", type="str", description="")],
        side_effect="read_only",
        tags=["echo"],
    )
    sandbox = SandboxResult(
        exit_code=0,
        passed=3,
        failed=0,
        observations=[{"type": "open", "path": "/tmp/x"}],
    )
    return SynthesisResult(
        success=True,
        spec_raw=ToolSpec(name="echo_tool", description="Echo input", when_to_use="x"),
        spec_enriched=enriched,
        tests="def test_x(): pass",
        final_code=_VALID_CODE,
        attempts=[
            SynthesisAttempt(round=1, code=_VALID_CODE, static_ok=True, sandbox=sandbox)
        ],
        sandbox_result=sandbox,
    )


def _make_fail_result() -> SynthesisResult:
    enriched = EnrichedToolSpec(
        name="bad_tool",
        description="d",
        when_to_use="x",
        examples=[],
        input_fields=[FieldSpec(name="q", type="str", description="")],
        output_fields=[FieldSpec(name="r", type="str", description="")],
    )
    fail_sandbox = SandboxResult(exit_code=1, failed=1, failure_messages=["test_x"])
    return SynthesisResult(
        success=False,
        spec_raw=ToolSpec(name="bad_tool", description="d", when_to_use="x"),
        spec_enriched=enriched,
        tests="def test_x(): pass",
        final_code="class X(BaseTool): pass",
        attempts=[
            SynthesisAttempt(round=1, code="x", static_ok=False, static_errors=["x"]),
            SynthesisAttempt(
                round=2, code="x", static_ok=True, sandbox=fail_sandbox
            ),
        ],
        sandbox_result=fail_sandbox,
        error="超過 3 次嘗試仍失敗",
    )


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s
    await engine.dispose()


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path: Path, monkeypatch):
    """每個 test 用獨立 generated_tools_dir + 乾淨 registry。"""
    monkeypatch.setattr(
        "app.config.settings.generated_tools_dir", str(tmp_path / "gen_tools")
    )
    tool_registry.clear()
    yield
    tool_registry.clear()


def _service(retriever: ToolRetriever | None = None) -> tuple[ApprovalService, FakeSender]:
    sender = FakeSender()
    notifier = Notifier(sender, default_chat_id="chat-1")
    svc = ApprovalService(notifier=notifier, retriever=retriever or _FakeRetriever())
    return svc, sender


class _FakeRetriever(ToolRetriever):
    """跳過真實 embedding。"""

    def __init__(self) -> None:
        super().__init__()
        self.added: list[str] = []
        self.removed: list[str] = []

    def add_tool(self, tool_id: str) -> None:  # type: ignore[override]
        self.added.append(tool_id)

    def remove_tool(self, tool_id: str) -> None:  # type: ignore[override]
        self.removed.append(tool_id)

    def build(self) -> None:  # type: ignore[override]
        return


async def test_submit_success_creates_awaiting_approval(session: AsyncSession):
    svc, sender = _service()
    task_id = await svc.submit(
        session,
        result=_make_success_result(),
        workspace_id="cs",
        triggered_by_query="客戶買了什麼",
        triggered_by_user="alan",
    )
    task = await session.get(ToolSynthesisTask, task_id)
    assert task is not None
    assert task.state == persistence.STATE_AWAITING_APPROVAL
    # Telegram 訊息有發
    assert len(sender.sent) == 1
    assert "echo_tool" in sender.sent[0]["text"]


async def test_submit_failure_routes_to_rescue(session: AsyncSession):
    svc, sender = _service()
    await svc.submit(
        session,
        result=_make_fail_result(),
        workspace_id="cs",
        triggered_by_query="x",
        triggered_by_user="alan",
    )
    rows = (await session.execute(select(ToolSynthesisTask))).scalars().all()
    assert len(rows) == 1
    assert rows[0].state == persistence.STATE_AWAITING_HUMAN_RESCUE
    # 訊息按鈕該是 rescue 那組
    flat = [b for row in sender.sent[0]["buttons"] for b in row]
    actions = {b.callback_data.split(":")[2] for b in flat}
    assert actions == {"retry", "refine", "abandon"}


async def test_approve_registers_tool(session: AsyncSession, tmp_path):
    retriever = _FakeRetriever()
    svc, _ = _service(retriever)
    task_id = await svc.submit(
        session,
        result=_make_success_result(),
        workspace_id="cs",
        triggered_by_query="x",
        triggered_by_user="alan",
    )
    tool_id = await svc.approve(session, task_id, reviewer="telegram:1")

    # task 狀態
    task = await session.get(ToolSynthesisTask, task_id)
    assert task.state == persistence.STATE_REGISTERED

    # GeneratedTool row
    gt = await session.get(GeneratedTool, tool_id)
    assert gt is not None
    assert gt.workspace_id == "cs"
    assert gt.scope == "workspace"
    assert gt.approved_by == "telegram:1"

    # 寫到檔案系統
    assert Path(gt.source_path).exists()

    # 註冊到 tool_registry
    assert tool_id in tool_registry.list_ids()
    assert tool_registry.workspace_of(tool_id) == "cs"

    # retriever 收到通知
    assert tool_id in retriever.added


async def test_reject_marks_discarded(session: AsyncSession):
    svc, _ = _service()
    task_id = await svc.submit(
        session,
        result=_make_success_result(),
        workspace_id="cs",
        triggered_by_query="x",
        triggered_by_user="alan",
    )
    await svc.reject(session, task_id, reviewer="telegram:1", note="not useful")
    task = await session.get(ToolSynthesisTask, task_id)
    assert task.state == persistence.STATE_DISCARDED
    rows = (await session.execute(select(ToolReviewHistory))).scalars().all()
    assert rows[0].action == "reject"


async def test_queue_refine_returns_to_code_generating(session: AsyncSession):
    svc, _ = _service()
    task_id = await svc.submit(
        session,
        result=_make_success_result(),
        workspace_id="cs",
        triggered_by_query="x",
        triggered_by_user="alan",
    )
    await svc.queue_refine(session, task_id, reviewer="telegram:1", hint="改用 httpx")
    task = await session.get(ToolSynthesisTask, task_id)
    assert task.state == persistence.STATE_CODE_GENERATING
    rev = (await session.execute(select(ToolReviewHistory))).scalars().first()
    assert rev.action == "refine_hint"
    assert rev.hint == "改用 httpx"


async def test_callback_handler_dispatches_to_approve(session: AsyncSession, tmp_path):
    retriever = _FakeRetriever()
    svc, sender = _service(retriever)
    task_id = await svc.submit(
        session,
        result=_make_success_result(),
        workspace_id="cs",
        triggered_by_query="x",
        triggered_by_user="alan",
    )
    sent_msg_id = sender.sent[0]["message_id"]

    # 模擬 session_factory：產出同一個 in-memory session
    class _Ctx:
        async def __aenter__(self):
            return session
        async def __aexit__(self, *a):
            return False

    handler = svc.make_callback_handler(lambda: _Ctx())
    await handler(
        ApprovalCallback(task_id=task_id, action="approve"),
        chat_id="chat-1",
        message_id=sent_msg_id,
    )

    task = await session.get(ToolSynthesisTask, task_id)
    assert task.state == persistence.STATE_REGISTERED
    # 訊息應該被 edit 成已處理
    assert len(sender.edits) == 1
    assert "已處理" in sender.edits[0]["text"]
