"""共用 API testing helpers（Phase 6 M7）。

提供：
  api_client(...)  AsyncClient with overridden get_session + in-memory DB
                  + integration.reset() 與 tool_registry.clear()

底線開頭：pytest 不會把這檔當測試收集。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import models  # noqa: F401 — register tables
from app.db.database import Base, get_session
from app.main import app
from app.synthesis import integration
from app.tools import registry as tool_registry


@pytest_asyncio.fixture
async def api_ctx() -> AsyncIterator[tuple[AsyncClient, async_sessionmaker[AsyncSession]]]:
    """Yield (AsyncClient, SessionLocal) — TestClient with in-memory DB + clean singletons。

    強制 llm_provider=mock：避免在使用者本機 .env 設了 groq 時打真 API。

    使用方式：
        async def test_x(api_ctx):
            client, SessionLocal = api_ctx
            ...
    """
    # 強制 mock LLM + 停用 Telegram bot，避免測試打外部 API
    from app.config import settings as _settings
    from app.providers import factory as _factory

    _orig_provider = _settings.llm_provider
    _orig_tg_token = _settings.tg_bot_token
    _settings.llm_provider = "mock"
    _settings.tg_bot_token = ""  # 強制走 FakeBot
    _factory.clear_cache()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session():
        async with SessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = _override_session
    integration.reset()
    tool_registry.clear()

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client, SessionLocal
    finally:
        app.dependency_overrides.clear()
        integration.reset()
        tool_registry.clear()
        await engine.dispose()
        _settings.llm_provider = _orig_provider
        _settings.tg_bot_token = _orig_tg_token
        _factory.clear_cache()


@asynccontextmanager
async def reuse_session_factory(SessionLocal):
    """讓 test 可以直接呼叫 integration.get_approval_service 但使用測試 SessionLocal。

    用 monkeypatch 配合，例如：
        monkeypatch.setattr(
            "app.synthesis.integration.load_all_active", _fake_load
        )
    """
    yield SessionLocal
