"""LangGraph node functions.

"fast" role for filter_gate/classify_theme, "deep" role for score_match/
extract_gaps (needs real judgment against the profile) -- see llm_config.py
for what model actually backs each role and how to switch providers. Every
LLM node logs tokens + latency to state.node_logs -- that's the observability
story for Phase 3's eval and for the cost/runtime comparison across providers.
"""
import re

from src.pipeline import profile_context as pc
from src.pipeline.llm_call import call as _call, load_prompt as _load_prompt, truncate as _truncate
from src.pipeline.schemas import (
    ExtractedJobFields,
    FilterGateResult,
    GapExtraction,
    JobBlurb,
    MatchScore,
    PipelineState,
    ThemeClassification,
)

# The title-word exclude rule is 100% mechanically checkable -- no LLM
# judgment needed. Enforcing it in code removes an entire hallucination
# class: testing on the 14 Aug batch found the LLM inventing "title
# contains Senior/Staff/..." for jobs whose titles plainly didn't (e.g.
# "AI Scientist, LLM Systems", "Founding AI Engineer"), and once
# extending the rule to a word ("Manager") that was never in it.


def normalize_node(state: PipelineState) -> dict:
    """Deterministic cleanup (strip HTML, collapse whitespace) plus an LLM
    backfill for title/company, but only when they're actually missing --
    manual URL-paste jobs where the user didn't type them in. Every other
    source (seed/adzuna/jsearch/serpapi) already has both, so this LLM call
    doesn't fire for them."""
    desc = state.description or ""
    desc = re.sub(r"<[^>]+>", " ", desc)
    desc = re.sub(r"\s+", " ", desc).strip()

    updates: dict = {"description": desc or None}

    needs_title = not state.title.strip()
    needs_company = not state.company.strip() or state.company.strip().lower() == "unknown"
    if (needs_title or needs_company) and desc:
        prompt = _load_prompt("extract_title_company").format(job_description=_truncate(desc))
        parsed, log = _call("fast", prompt, ExtractedJobFields)
        updates["node_logs"] = [log]
        if needs_title and parsed.title:
            updates["title"] = parsed.title
        if needs_company and parsed.company:
            updates["company"] = parsed.company

    return updates


def generate_blurb_node(state: PipelineState) -> dict:
    """Runs unconditionally right after normalize (before the filter_gate
    short-circuit) so every job -- including ones that end up excluded --
    gets a card blurb for the Board's "show excluded" audit view too."""
    prompt = _load_prompt("generate_blurb").format(
        job_title=state.title,
        job_company=state.company,
        job_description=_truncate(state.description),
    )
    parsed, log = _call("fast", prompt, JobBlurb)
    return {"blurb": parsed.blurb, "node_logs": [log]}


def filter_gate_node(state: PipelineState) -> dict:
    # No title-word rule: seniority words in a title ("Senior", "Lead", "Staff")
    # say little on their own, so seniority is judged from the requirements
    # (e.g. years of experience in filters.md) and in match scoring instead.
    prompt = _load_prompt("filter_gate").format(
        filters=pc.load_filters(),
        job_title=state.title,
        job_company=state.company,
        job_location=state.location or "(not specified)",
        job_level=state.level or "(not specified)",
        job_description=_truncate(state.description),
    )
    parsed, log = _call("fast", prompt, FilterGateResult)
    return _soften_for_manual(state, {"decision": parsed.decision, "filter_reasons": parsed.reasons, "node_logs": [log]})


def _soften_for_manual(state: PipelineState, result: dict) -> dict:
    """Exclude rules exist to skip obvious misses among bulk API results cheaply.
    A job the user added by hand was already chosen, so a rule hit becomes a
    visible warning (flag) and screening continues to theme/match/gaps."""
    if state.manual and result["decision"] == "exclude":
        result["decision"] = "flag"
        result["filter_reasons"] = [
            "Would be excluded for bulk-ingested jobs; shown as a warning because you added this job by hand."
        ] + result["filter_reasons"]
    return result


def classify_theme_node(state: PipelineState) -> dict:
    if state.forced_theme:
        return {
            "theme": state.forced_theme,
            "theme_rationale": f"Theme {state.forced_theme} forced manually by the user (classifier skipped).",
            "node_logs": [],
        }
    prompt = _load_prompt("classify_theme").format(
        themes_summary=pc.load_all_themes_summary(),
        job_title=state.title,
        job_company=state.company,
        job_location=state.location or "(not specified)",
        job_description=_truncate(state.description),
    )
    parsed, log = _call("fast", prompt, ThemeClassification)
    return {"theme": parsed.theme, "theme_rationale": parsed.rationale, "node_logs": [log]}


def score_match_node(state: PipelineState) -> dict:
    prompt = _load_prompt("score_match").format(
        theme_profile=pc.load_theme(state.theme),
        constraints=pc.load_constraints(),
        job_title=state.title,
        job_company=state.company,
        job_location=state.location or "(not specified)",
        job_level=state.level or "(not specified)",
        job_description=_truncate(state.description),
    )
    parsed, log = _call("deep", prompt, MatchScore)
    return {
        "match_level": parsed.match_level,
        "match_rationale": parsed.rationale,
        "target_lane": parsed.target_lane,
        "node_logs": [log],
    }


def extract_gaps_node(state: PipelineState) -> dict:
    prompt = _load_prompt("extract_gaps").format(
        theme_profile=pc.load_theme(state.theme),
        job_title=state.title,
        job_company=state.company,
        job_description=_truncate(state.description),
    )
    parsed, log = _call("deep", prompt, GapExtraction)
    return {"gaps": parsed.gaps, "node_logs": [log]}
