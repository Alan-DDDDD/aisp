"""共用 fake objects（Phase 6 testing 用）。

底線開頭表示「不是 test，是 helper」—— pytest 不會把這檔當測試收集。
"""

from __future__ import annotations

from app.providers.base import GenerationRequest, GenerationResponse, LLMProvider
from app.synthesis.schemas import ToolCandidate
from app.synthesis.tool_retriever import ToolRetriever


class ScriptedProvider(LLMProvider):
    """讓測試指定每次 generate() 回傳什麼 text。

    用法：
        provider = ScriptedProvider(responses=[
            '{"steps": [...]}',   # planner 回應
            '{"decisions": [...]}',  # judge 回應
        ])
    依序消費；超出長度回空字串。
    """

    name = "scripted"

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[GenerationRequest] = []

    async def generate(self, req: GenerationRequest) -> GenerationResponse:
        self.calls.append(req)
        text = self._responses.pop(0) if self._responses else ""
        return GenerationResponse(
            text=text,
            model=req.model or "scripted",
            usage={},
            latency_ms=0,
        )


class FakeRetriever(ToolRetriever):
    """測試用 retriever：預先注入 step_description → candidates 對照表。

    沒命中時回空，方便驗證 shortcut_low（GAP）路徑。
    """

    def __init__(self, mapping: dict[str, list[ToolCandidate]] | None = None) -> None:
        super().__init__()
        self._mapping: dict[str, list[ToolCandidate]] = mapping or {}

    def set(self, step_description: str, candidates: list[ToolCandidate]) -> None:
        self._mapping[step_description] = candidates

    def is_built(self) -> bool:  # type: ignore[override]
        return True

    def build(self) -> None:  # type: ignore[override]
        return

    def retrieve(  # type: ignore[override]
        self,
        step_description: str,
        top_k: int = 5,
        *,
        workspace_id: str | None = None,  # noqa: ARG002 — fake 不關心 scoping
    ) -> list[ToolCandidate]:
        cands = self._mapping.get(step_description, [])
        return cands[:top_k]
