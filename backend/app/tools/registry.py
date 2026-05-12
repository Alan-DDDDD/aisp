from app.tools.base import BaseTool

_registry: dict[str, BaseTool] = {}


def register(tool: BaseTool) -> None:
    if tool.id in _registry:
        raise ValueError(f"Tool already registered: {tool.id}")
    _registry[tool.id] = tool


def get(tool_id: str) -> BaseTool:
    if tool_id not in _registry:
        raise KeyError(f"Tool not found: {tool_id}")
    return _registry[tool_id]


def list_ids() -> list[str]:
    return list(_registry.keys())


def clear() -> None:
    _registry.clear()
