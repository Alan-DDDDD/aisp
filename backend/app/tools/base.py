from abc import ABC, abstractmethod

from pydantic import BaseModel

from app.schemas.agent import AgentContext


class BaseTool(ABC):
    """所有 tool 的共同契約。

    Agent 是「決策」，Tool 是「動作」。Tool 由 agent 主動呼叫，
    且每次呼叫都會被 orchestrator 紀錄到 tool_invocations。
    """

    id: str
    description: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]

    @abstractmethod
    async def call(self, ctx: AgentContext, payload: BaseModel) -> BaseModel:
        raise NotImplementedError
