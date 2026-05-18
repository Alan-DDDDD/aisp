"""Phase 6 M3 — callback_data 解析。"""

from __future__ import annotations

from app.telegram.callback_router import (
    ApprovalCallback,
    GrayCallback,
    parse_callback,
)


def test_parse_gray_use():
    out = parse_callback("gz:abc123:use:kb_search")
    assert isinstance(out, GrayCallback)
    assert out.interaction_id == "abc123"
    assert out.kind == "use"
    assert out.tool_id == "kb_search"


def test_parse_gray_gap():
    out = parse_callback("gz:abc123:gap")
    assert isinstance(out, GrayCallback)
    assert out.kind == "gap"
    assert out.tool_id is None


def test_parse_approval_actions():
    for action in ("approve", "reject", "refine", "retry", "abandon"):
        out = parse_callback(f"ap:task-1:{action}")
        assert isinstance(out, ApprovalCallback)
        assert out.task_id == "task-1"
        assert out.action == action


def test_parse_invalid_returns_none():
    assert parse_callback("") is None
    assert parse_callback("nope") is None
    assert parse_callback("gz") is None
    assert parse_callback("gz:abc") is None
    assert parse_callback("gz:abc:unknown") is None
    assert parse_callback("ap:t:badaction") is None
    assert parse_callback("xx:y:z") is None
