"""Shared LLM-call plumbing for every component (screening, CV, letters,
archetypes, ...): structured calls with token/latency logging, and prompt
loading from each component's own prompts/ folder.
"""
import time
from pathlib import Path

from src.llm.config import JSON_SCHEMA_ROLES, get_llm, model_label
from src.llm.schemas import NodeLog

SRC_DIR = Path(__file__).resolve().parent.parent


def load_prompt(name: str) -> str:
    """'component/prompt' -> src/<component>/prompts/<prompt>.md, e.g. 'screening/score_match'."""
    component, _, prompt = name.partition("/")
    return (SRC_DIR / component / "prompts" / f"{prompt}.md").read_text()


def truncate(text: str | None, n: int = 4000) -> str:
    if not text:
        return "(no description provided)"
    return text[:n]


def call(role: str, prompt: str, schema: type, provider: str | None = None, method: str | None = None):
    """method overrides the role's default: "json_schema" (native structured
    outputs) is more reliable for large nested schemas, where tool calling
    occasionally returns a list field as plain text."""
    llm = get_llm(role, provider=provider)
    method = method or ("json_schema" if role in JSON_SCHEMA_ROLES else "function_calling")
    structured = llm.with_structured_output(schema, include_raw=True, method=method)
    start = time.monotonic()
    result = structured.invoke(prompt)
    latency_ms = (time.monotonic() - start) * 1000

    parsed = result["parsed"]
    if parsed is None:
        # with include_raw=True a validation failure comes back as parsed=None
        # instead of raising; surface why rather than failing later on None.
        raise ValueError(f"{schema.__name__}: structured output didn't validate: {result.get('parsing_error')}")
    usage = getattr(result["raw"], "usage_metadata", None) or {}
    log = NodeLog(
        node=schema.__name__,
        model=model_label(role, provider=provider),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        latency_ms=latency_ms,
    )
    return parsed, log
