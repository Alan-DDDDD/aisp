"""Workflow 變數解析測試。"""

from app.workflow.resolver import collect_refs, resolve


def test_resolve_pure_reference_scalar():
    scope = {"event": {"message": "hi"}}
    assert resolve("$event.message", scope) == "hi"


def test_resolve_pure_reference_dict():
    scope = {"router": {"intent": "x", "category": "loan"}}
    assert resolve("$router", scope) == {"intent": "x", "category": "loan"}


def test_resolve_string_interpolation():
    scope = {"event": {"message": "車貸"}}
    out = resolve("使用者問：$event.message", scope)
    assert out == "使用者問：車貸"


def test_resolve_dict_recurses():
    scope = {"event": {"message": "hi"}, "context": {"workspace_id": "cs"}}
    template = {
        "query": "$event.message",
        "workspace_id": "$context.workspace_id",
        "top_k": 5,
        "filter": {"q": "$event.message"},
    }
    out = resolve(template, scope)
    assert out == {
        "query": "hi",
        "workspace_id": "cs",
        "top_k": 5,
        "filter": {"q": "hi"},
    }


def test_resolve_missing_returns_none():
    assert resolve("$nope.x", {}) is None


def test_collect_refs_roots():
    template = {
        "query": "$event.message",
        "workspace_id": "$context.workspace_id",
        "intent": "$router",
        "docs": "$knowledge.docs",
    }
    roots = collect_refs(template)
    assert roots == {"event", "context", "router", "knowledge"}


def test_collect_refs_list():
    roots = collect_refs(["$a.b", {"x": "$c"}, 5, "no ref"])
    assert roots == {"a", "c"}
