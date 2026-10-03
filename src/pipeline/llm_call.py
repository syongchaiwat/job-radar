"""Shared LLM-call plumbing, used by both graph nodes (nodes.py) and
standalone non-graph LLM functions (breakdown.py) -- extracted so the
latter doesn't need to import underscore-prefixed names from nodes.py.
"""
import time
from pathlib import Path

from src.pipeline.llm_config import JSON_SCHEMA_ROLES, get_llm, model_label
from src.pipeline.schemas import NodeLog

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / f"{name}.md").read_text()


def truncate(text: str | None, n: int = 4000) -> str:
    if not text:
        return "(no description provided)"
    return text[:n]


def call(role: str, prompt: str, schema: type, provider: str | None = None):
    llm = get_llm(role, provider=provider)
    method = "json_schema" if role in JSON_SCHEMA_ROLES else "function_calling"
    structured = llm.with_structured_output(schema, include_raw=True, method=method)
    start = time.monotonic()
    result = structured.invoke(prompt)
    latency_ms = (time.monotonic() - start) * 1000

    parsed = result["parsed"]
    usage = getattr(result["raw"], "usage_metadata", None) or {}
    log = NodeLog(
        node=schema.__name__,
        model=model_label(role, provider=provider),
        input_tokens=usage.get("input_tokens", 0),
        output_tokens=usage.get("output_tokens", 0),
        latency_ms=latency_ms,
    )
    return parsed, log
