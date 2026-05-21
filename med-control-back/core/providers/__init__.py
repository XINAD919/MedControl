import os

from .base import BaseProvider

_PROVIDERS: dict[str, type[BaseProvider]] = {}

try:
    from .ollama import OllamaProvider
    _PROVIDERS["ollama"] = OllamaProvider
except ImportError:
    pass

try:
    from .anthropic import AnthropicProvider
    _PROVIDERS["anthropic"] = AnthropicProvider
except ImportError:
    pass


def create_provider(
    name: str | None = None,
    model: str | None = None,
    fast: bool = False,
) -> BaseProvider:
    name = name or os.getenv("LLM_PROVIDER", "anthropic")
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Proveedor desconocido: '{name}'. Disponibles: {list(_PROVIDERS)}")

    kwargs: dict = {}
    if model:
        kwargs["model"] = model
    elif fast and name == "anthropic":
        kwargs["model"] = os.getenv("ANTHROPIC_FAST_MODEL", "claude-haiku-4-5-20251001")
    elif llm_model := os.getenv("LLM_MODEL"):
        kwargs["model"] = llm_model

    if name == "ollama":
        if host := os.getenv("OLLAMA_HOST"):
            kwargs["host"] = host
    elif api_key := os.getenv(f"{name.upper()}_API_KEY"):
        kwargs["api_key"] = api_key

    return cls(**kwargs)
