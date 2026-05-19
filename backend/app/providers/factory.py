from app.config import settings
from app.providers.base import LLMProvider
from app.providers.cerebras import CerebrasProvider
from app.providers.groq import GroqProvider
from app.providers.mock import MockProvider

_cache: dict[str, LLMProvider] = {}


_GROQ_DEFAULT_MODEL = "llama-3.1-8b-instant"
# Cerebras free tier 上能跑、且中文/通用任務都行的最大模型。
# 替代：gpt-oss-120b（OpenAI 開源）或 llama3.1-8b（小任務）。
_CEREBRAS_DEFAULT_MODEL = "qwen-3-235b-a22b-instruct-2507"


def get_provider(name: str | None = None) -> LLMProvider:
    key = (name or settings.llm_provider).lower()
    if key in _cache:
        return _cache[key]

    provider: LLMProvider
    if key == "mock":
        provider = MockProvider()
    elif key == "groq":
        if not settings.groq_api_key:
            raise ValueError("groq provider 需要 GROQ_API_KEY")
        provider = GroqProvider(
            api_key=settings.groq_api_key,
            default_model=settings.llm_model or _GROQ_DEFAULT_MODEL,
            verify_ssl=settings.llm_ssl_verify,
        )
    elif key == "cerebras":
        if not settings.cerebras_api_key:
            raise ValueError("cerebras provider 需要 CEREBRAS_API_KEY")
        # 注意：cerebras default_model 不讀 settings.llm_model —— 那個欄位專屬全域
        # provider 的預設；多 provider 共存時各家 default 互不干擾。
        provider = CerebrasProvider(
            api_key=settings.cerebras_api_key,
            default_model=_CEREBRAS_DEFAULT_MODEL,
            verify_ssl=settings.llm_ssl_verify,
        )
    elif key == "ollama":
        raise NotImplementedError("Ollama provider 將於後續加入")
    elif key == "gemini":
        raise NotImplementedError("Gemini provider 將於後續加入")
    elif key == "openrouter":
        raise NotImplementedError("OpenRouter provider 將於後續加入")
    else:
        raise ValueError(f"Unknown LLM provider: {key}")

    _cache[key] = provider
    return provider


def pick_provider(role_provider: str = "") -> LLMProvider:
    """Phase 6 多 provider routing：role 沒指定時 fallback 到 llm_provider 全域。

    用在 bootstrap：把 composer / synthesis / judge 各自指到不同 provider，
    其他小 agent（router / policy 等）共用全域。
    """
    return get_provider(role_provider) if role_provider else get_provider()


def clear_cache() -> None:
    """測試用：清掉 provider 快取。"""
    _cache.clear()
