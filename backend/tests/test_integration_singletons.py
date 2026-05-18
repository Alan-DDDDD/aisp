"""Phase 6 M7 — integration singletons + lifespan helpers。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db import models  # noqa: F401
from app.db.database import Base
from app.synthesis import integration
from app.telegram.bot import FakeBot


def test_default_bot_is_fake_when_token_empty(monkeypatch):
    """無 TG_BOT_TOKEN → 取得 FakeBot，可安全在測試環境跑。"""
    monkeypatch.setattr("app.config.settings.tg_bot_token", "")
    integration.reset()
    bot = integration.get_bot()
    assert isinstance(bot, FakeBot)


def test_singletons_are_shared(monkeypatch):
    monkeypatch.setattr("app.config.settings.tg_bot_token", "")
    integration.reset()
    a = integration.get_approval_service()
    b = integration.get_approval_service()
    assert a is b
    n1 = integration.get_notifier()
    n2 = integration.get_notifier()
    assert n1 is n2


def test_reset_clears_singletons(monkeypatch):
    monkeypatch.setattr("app.config.settings.tg_bot_token", "")
    integration.reset()
    bot1 = integration.get_bot()
    integration.reset()
    bot2 = integration.get_bot()
    assert bot1 is not bot2


async def test_on_startup_loads_generated_tools_no_telegram(monkeypatch, tmp_path):
    """無 TG_BOT_TOKEN 時 on_startup 仍應跑 load_all_active 不爆。"""
    monkeypatch.setattr("app.config.settings.tg_bot_token", "")
    monkeypatch.setattr(
        "app.config.settings.generated_tools_dir", str(tmp_path / "gen")
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    integration.reset()
    # 不 raise 即算過
    await integration.on_startup(SessionLocal)
    await integration.on_shutdown()
    await engine.dispose()
