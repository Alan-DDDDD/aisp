"""Phase 6 M3 — PendingRequests future store。"""

from __future__ import annotations

import asyncio

import pytest

from app.telegram.pending import PendingRequests


async def test_create_then_complete_returns_result():
    store = PendingRequests()
    entry = await store.create(purpose="test")

    async def _completer():
        await asyncio.sleep(0.01)
        await store.complete(entry.interaction_id, {"x": 1})

    asyncio.create_task(_completer())
    result = await store.wait(entry.interaction_id, timeout=1.0)
    assert result == {"x": 1}
    # complete 後 entry 應該被清掉
    assert store.size() == 0


async def test_wait_unknown_id_raises():
    store = PendingRequests()
    with pytest.raises(KeyError):
        await store.wait("never_existed", timeout=0.1)


async def test_wait_timeout_cleans_entry():
    store = PendingRequests()
    entry = await store.create(purpose="t")
    with pytest.raises(asyncio.TimeoutError):
        await store.wait(entry.interaction_id, timeout=0.05)
    # timeout 後清掉，避免記憶體洩漏
    assert store.size() == 0


async def test_complete_unknown_returns_false():
    store = PendingRequests()
    ok = await store.complete("nope", {"x": 1})
    assert ok is False


async def test_complete_twice_is_noop():
    store = PendingRequests()
    entry = await store.create(purpose="t")
    await store.complete(entry.interaction_id, {"x": 1})
    ok = await store.complete(entry.interaction_id, {"x": 2})
    # 第二次 complete 應該識別 future 已 done（其實 entry 已被刪），回 False
    assert ok is False


async def test_gc_clears_old_entries():
    store = PendingRequests()
    await store.create(purpose="a")
    await store.create(purpose="b")
    # 立即 gc 不該動到任何 entry（age=0）
    n = await store.gc(max_age_s=10.0)
    assert n == 0
    assert store.size() == 2
    # 用 age=0.0 強制全清
    n = await store.gc(max_age_s=-1.0)
    assert n == 2
    assert store.size() == 0
