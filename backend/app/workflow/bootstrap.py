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
from app.providers.factory import get_provider
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
    """Phase 6 完整套件：Router / Knowledge / Policy / Tone / Risk / Composer / TicketDecision / ClauseAnalyzer。"""
    agent_registry.clear()
    register_tools()
    provider = get_provider()
    agent_registry.register(RouterAgent(provider=provider))
    agent_registry.register(KnowledgeAgent())
    agent_registry.register(PolicyAgent(provider=provider))
    agent_registry.register(ToneAgent(provider=provider))
    agent_registry.register(RiskAgent(provider=provider))
    agent_registry.register(ComposerAgent(provider=provider))
    agent_registry.register(TicketDecisionAgent(provider=provider))
    agent_registry.register(ClauseAnalyzerAgent(provider=provider))
    agent_registry.register(ToolAgent(provider=provider))
    log.info("Registered default agents: %s", agent_registry.list_ids())
