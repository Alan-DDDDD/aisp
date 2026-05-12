from abc import ABC, abstractmethod

from pydantic import BaseModel

from app.schemas.agent import AgentContext


class BaseAgent(ABC):
    """所有 agent 的共同契約。

    - id 是 agent 的唯一識別，會被 workflow YAML 用 `agent: <id>` 引用
    - input_schema / output_schema 用於 runtime 驗證與 trace 紀錄
    """

    id: str
    input_schema: type[BaseModel]
    output_schema: type[BaseModel]

    @abstractmethod
    async def run(self, ctx: AgentContext, payload: BaseModel) -> BaseModel:
        """執行 agent。payload 必須是 input_schema 的實例，回傳值必須是 output_schema。"""
        raise NotImplementedError
