"""Phase 6 M6 — registry_loader：寫檔 → import → register；以及啟動載入。"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import models  # noqa: F401
from app.db.database import Base
from app.db.models import GeneratedTool, ToolSynthesisTask
from app.synthesis.registry_loader import install_from_source, load_all_active
from app.synthesis.tool_retriever import ToolRetriever
from app.tools import registry as tool_registry

_GOOD_CODE = '''
from __future__ import annotations

from pydantic import BaseModel

from app.schemas.agent import AgentContext
from app.tools.base import BaseTool, SideEffect, ToolExample


class _In(BaseModel):
    q: str = ""


class _Out(BaseModel):
    r: str = ""


class GenEchoTool(BaseTool):
    id = "gen_echo"
    version = "1.0.0"
    source = "generated"

    description = "Generated echo for tests."
    when_to_use = "test"
    when_NOT_to_use = "prod"
    examples = [ToolExample(scenario="x", input={"q": ""}, output={"r": ""})]
    input_schema = _In
    output_schema = _Out
    side_effect = SideEffect.READ_ONLY
    requires_approval = False
    tags = ["test"]

    async def call(self, ctx: AgentContext, payload: _In) -> _Out:
        return _Out(r=payload.q)
'''


class _FakeRetriever(ToolRetriever):
    def __init__(self) -> None:
        super().__init__()
        self.added: list[str] = []

    def add_tool(self, tool_id: str) -> None:  # type: ignore[override]
        self.added.append(tool_id)

    def remove_tool(self, tool_id: str) -> None:  # type: ignore[override]
        pass

    def build(self) -> None:  # type: ignore[override]
        return


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "app.config.settings.generated_tools_dir", str(tmp_path / "gen")
    )
    tool_registry.clear()
    yield
    tool_registry.clear()


def test_install_from_source_writes_imports_registers():
    retriever = _FakeRetriever()
    path = install_from_source(
        "gen_echo", _GOOD_CODE, workspace_id="cs", retriever=retriever
    )
    assert path.exists()
    assert path.read_text(encoding="utf-8") == _GOOD_CODE
    assert "gen_echo" in tool_registry.list_ids()
    assert tool_registry.workspace_of("gen_echo") == "cs"
    assert "gen_echo" in retriever.added


def test_install_from_source_rejects_bad_static_check():
    bad_code = "import subprocess\n\nclass X: pass\n"
    with pytest.raises(RuntimeError) as exc:
        install_from_source("x", bad_code, workspace_id=None)
    assert "static check" in str(exc.value)


def test_install_from_source_overrides_id_with_db():
    """tool 內 id 跟 DB tool_id 不符時，以 DB 為準（防 DB 被改後不一致）。"""
    retriever = _FakeRetriever()
    code = _GOOD_CODE.replace('id = "gen_echo"', 'id = "wrong_id"')
    install_from_source("gen_echo", code, workspace_id=None, retriever=retriever)
    assert "gen_echo" in tool_registry.list_ids()
    assert "wrong_id" not in tool_registry.list_ids()


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as s:
        yield s
    await engine.dispose()


async def test_load_all_active_brings_back_approved_tools(session: AsyncSession, tmp_path):
    # 1) 模擬之前 approve 過：寫一個檔 + DB row
    src = tmp_path / "gen" / "gen_echo.py"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(_GOOD_CODE, encoding="utf-8")

    # 對應的 ToolSynthesisTask + GeneratedTool
    task = ToolSynthesisTask(id="syn-1", workspace_id="cs", state="REGISTERED")
    session.add(task)
    session.add(
        GeneratedTool(
            id="gen_echo",
            synthesis_task_id="syn-1",
            workspace_id="cs",
            description="x",
            source_path=str(src),
            approved_by="alan",
            approved_at=datetime.now(UTC),
            status="active",
        )
    )
    await session.commit()

    retriever = _FakeRetriever()
    count = await load_all_active(session, retriever=retriever)
    assert count == 1
    assert "gen_echo" in tool_registry.list_ids()
    assert tool_registry.workspace_of("gen_echo") == "cs"


async def test_load_all_active_skips_missing_file(session: AsyncSession):
    """檔案不見 → 跳過該筆，不影響其他。"""
    task = ToolSynthesisTask(id="syn-x", workspace_id="cs", state="REGISTERED")
    session.add(task)
    session.add(
        GeneratedTool(
            id="missing",
            synthesis_task_id="syn-x",
            workspace_id="cs",
            description="x",
            source_path="/nope/never/here.py",
            approved_by="alan",
            approved_at=datetime.now(UTC),
            status="active",
        )
    )
    await session.commit()

    count = await load_all_active(session, retriever=_FakeRetriever())
    assert count == 0
    assert "missing" not in tool_registry.list_ids()
