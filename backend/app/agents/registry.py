from app.agents.base import BaseAgent

_registry: dict[str, BaseAgent] = {}


def register(agent: BaseAgent) -> None:
    if agent.id in _registry:
        raise ValueError(f"Agent already registered: {agent.id}")
    _registry[agent.id] = agent


def get(agent_id: str) -> BaseAgent:
    if agent_id not in _registry:
        raise KeyError(f"Agent not found: {agent_id}")
    return _registry[agent_id]


def list_ids() -> list[str]:
    return list(_registry.keys())


def clear() -> None:
    _registry.clear()
