"""Central LLM provider/model config. Every node calls get_llm(role) where role
is "fast" (filter_gate) or "deep" (score_match, extract_gaps).

Switch providers via LLM_PROVIDER in .env -- every node routes through here,
so swapping Anthropic <-> local Ollama is a one-file change, not a rewrite.

On 16GB unified memory (Apple Silicon shares RAM across OS/apps/model), two
resident 8B-class models would force Ollama to reload weights between calls,
which costs more wall-clock time than just running one model everywhere --
so "fast" and "deep" point at the same local model by default. Anthropic mode
keeps the original Haiku/Sonnet split since token cost, not RAM, is the
constraint there.
"""
import os
from functools import lru_cache

PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic").lower()

# "critique" is the CV loop's reviewer: a stronger model than the drafter
# ("deep"), since every quality problem seen on Claude was in the critique.
ANTHROPIC_MODELS = {"fast": "claude-haiku-4-5-20251001", "deep": "claude-sonnet-5", "critique": "claude-opus-5-5"}

# Opus 5.5 rejects forced tool_choice, which LangChain's default
# function_calling structured output relies on -- use native structured outputs.
JSON_SCHEMA_ROLES = {"critique"}

_ollama_default = os.environ.get("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_MODELS = {
    "fast": os.environ.get("OLLAMA_MODEL_FAST", _ollama_default),
    "deep": os.environ.get("OLLAMA_MODEL_DEEP", _ollama_default),
    "critique": os.environ.get("OLLAMA_MODEL_DEEP", _ollama_default),
}


@lru_cache(maxsize=8)
def get_llm(role: str, provider: str | None = None):
    """provider overrides LLM_PROVIDER for this one call -- used by the CV
    draft/critique loop, which forces "anthropic" regardless of the global
    setting (local Ollama was tested and produced fabricated CVs; the
    screening pipeline's simpler per-job classification task doesn't have
    that problem, so it keeps the cheaper default)."""
    provider = (provider or PROVIDER).lower()
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=OLLAMA_MODELS[role],
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0,
            reasoning=False,
        )
    from langchain_anthropic import ChatAnthropic

    # temperature is deprecated/rejected by newer Claude models (e.g. claude-sonnet-5) --
    # omit it rather than hardcode 0, since passing it at all is now a 400 for some models.
    if role == "critique":
        # Opus 5.5 defaults to effort "medium"; review quality is the point of this role.
        # max_tokens explicitly: langchain-anthropic doesn't know this model id and
        # falls back to 4096, which truncated long outputs (thinking shares the budget).
        return ChatAnthropic(model=ANTHROPIC_MODELS[role], output_config={"effort": "high"}, max_tokens=32000)
    return ChatAnthropic(model=ANTHROPIC_MODELS[role])


def model_label(role: str, provider: str | None = None) -> str:
    """For NodeLog: which actual model is behind this role right now."""
    provider = (provider or PROVIDER).lower()
    return (OLLAMA_MODELS if provider == "ollama" else ANTHROPIC_MODELS)[role]
