"""啟動時把目前 Phase 需要的 agents 與 tools 註冊進 registry。"""

import logging

from app.agents import registry as agent_registry
from app.agents.clause_analyzer import ClauseAnalyzerAgent
from app.agents.composer import ComposerAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.policy import PolicyAgent
from app.agents.risk import RiskAgent
from app.agents.router import RouterAgent
from app.agents.ticket_decision import TicketDecisionAgent
from app.agents.tone import ToneAgent
from app.agents.tool_agent import ToolAgent
from app.config import settings
from app.providers.factory import pick_provider
from app.synthesis import integration as synth_integration
from app.synthesis.gap_detector import GapDetector
from app.synthesis.judge import Judge
from app.synthesis.orchestrator import SynthesisOrchestrator
from app.synthesis.planner import Planner
from app.tools import registry as tool_registry
from app.tools.kb_search import KBSearchTool
from app.tools.ticket_create import TicketCreateTool

log = logging.getLogger(__name__)


def register_tools() -> None:
    tool_registry.clear()
    tool_registry.register(KBSearchTool())
    tool_registry.register(TicketCreateTool())
    log.info("Registered tools: %s", tool_registry.list_ids())


def register_default_agents() -> None:
    """Phase 6 完整套件 + 多 provider routing（PLAN §22.4.5）。

    Provider 分派：
      - default：router / policy / tone / risk / ticket_decision / clause_analyzer / knowledge
      - composer：可走 cerebras（COMPOSER_PROVIDER=cerebras）拿 1M TPD
      - planner（spec_enricher / code_gen / test_gen / arg_gen）：高 token 量，建議走 cerebras
      - judge：小 8B 任務，建議留 groq（額度本來吃不滿）

    空字串 = 用 settings.llm_provider 全域 default。
    """
    agent_registry.clear()
    register_tools()

    default_provider = pick_provider()
    composer_provider = pick_provider(settings.composer_provider)
    planner_provider = pick_provider(settings.gap_planner_provider)
    judge_provider = pick_provider(settings.gap_judge_provider)

    log.info(
        "LLM routing — default=%s, composer=%s, planner=%s, judge=%s",
        default_provider.name,
        composer_provider.name,
        planner_provider.name,
        judge_provider.name,
    )

    agent_registry.register(RouterAgent(provider=default_provider))
    agent_registry.register(KnowledgeAgent())
    agent_registry.register(PolicyAgent(provider=default_provider))
    agent_registry.register(ToneAgent(provider=default_provider))
    agent_registry.register(RiskAgent(provider=default_provider))
    agent_registry.register(ComposerAgent(provider=composer_provider))
    agent_registry.register(TicketDecisionAgent(provider=default_provider))
    agent_registry.register(ClauseAnalyzerAgent(provider=default_provider))

    # ToolAgent + 合成能力（TA3）：lazy 解析 SessionLocal 避免 import 時 init_db 未跑
    from app.db.database import SessionLocal

    # GapDetector 把 Planner / Judge 拆開，分別注入不同 provider
    gap_detector = GapDetector(
        provider=planner_provider,  # 留作 default — 我們會顯式注入 planner+judge 蓋掉
        planner=Planner(provider=planner_provider),
        judge=Judge(provider=judge_provider),
    )

    agent_registry.register(
        ToolAgent(
            provider=planner_provider,  # arg_gen 用，量小、共用 planner provider 即可
            gap_detector=gap_detector,
            orchestrator=SynthesisOrchestrator(provider=planner_provider),
            approval_service=synth_integration.get_approval_service(),
            session_factory=SessionLocal,
        )
    )

    log.info("Registered default agents: %s", agent_registry.list_ids())
