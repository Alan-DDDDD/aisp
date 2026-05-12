from app.config import settings
from app.providers.base import LLMProvider
from app.providers.groq import GroqProvider
from app.providers.mock import MockProvider

_cache: dict[str, LLMProvider] = {}


_GROQ_DEFAULT_MODEL = "llama-3.1-8b-instant"


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


def clear_cache() -> None:
    """測試用：清掉 provider 快取。"""
    _cache.clear()
