"""LangGraph node functions for the CV draft/critique loop.

Drafting uses the "deep" role (Sonnet), critiquing the stronger "critique"
role (Opus, see llm_config.py): the reviewer was where every quality problem
showed up (false fabrication accusations), so it gets the better model. See
cv_graph.py for the loop topology these are wired into.

Both calls force provider="anthropic", overriding LLM_PROVIDER: tested
against local Ollama (qwen3:8b) on 2026-09-24 and it fabricated a wrong
name, wrong contact details, an invented degree, and skills with no
grounding in any project's Tools field, all while the critique scored it
honesty=5/approve. Real Anthropic (Sonnet, via the "deep" role) caught
everything correctly and produced fully-grounded output in the same test.
This isn't a cost-vs-quality knob -- Ollama is a real safety problem for
this specific task, not just a cheaper option.
"""
import re

from src.profile import cv_template as cvpc
from src.profile import context as pc
from src.llm.call import call as _call, load_prompt as _load_prompt, truncate as _truncate
from src.llm.schemas import CVCritique, CVDraftOutput, CVDraftState


def _format_previous_feedback(state: CVDraftState) -> str:
    if state.attempt_count == 0:
        return state.seed_notes or "(none -- this is the first draft)"
    lines = [
        f"Scores last time -- relevance {state.relevance_score}/5, honesty {state.honesty_score}/5, "
        f"impact {state.impact_score}/5, clarity {state.clarity_score}/5, "
        f"keyword alignment {state.keyword_alignment_score}/5.",
        f"Feedback: {state.overall_feedback}",
    ]
    if state.unresolved_gaps:
        lines.append("Unresolved gaps flagged: " + "; ".join(state.unresolved_gaps))
    return "\n".join(lines)


def _normalize(text: str) -> str:
    return re.sub(r"[\s*_`]+", " ", text).strip().lower()


def _verified_quotes(quotes: list[str], draft: str) -> list[str]:
    haystack = _normalize(draft)
    return [q for q in quotes if len(_normalize(q)) >= 3 and _normalize(q) in haystack]


MIN_SKILL_GROUPS, MAX_SKILL_GROUPS = 3, 5
MAX_SUMMARY_WORDS = 60  # ~4 lines at the PDF's 10pt body size
_COMPANY_STOPWORDS = {"the", "and", "ag", "gmbh", "sa", "ltd", "inc", "group", "center", "centre", "for", "of", "zurich"}


def _summary_text(draft: str) -> str | None:
    m = re.search(r"^## Summary\s*$(.*?)(?=^## |\Z)", draft, re.M | re.S)
    return m.group(1).strip() if m else None


def _summary_problems(draft: str, company: str) -> list[str]:
    """Deterministic summary rules: length cap and no naming the target company."""
    summary = _summary_text(draft)
    if summary is None:
        return []
    problems = []
    words = len(summary.split())
    if words > MAX_SUMMARY_WORDS:
        problems.append(f"Summary is {words} words; cut it to at most {MAX_SUMMARY_WORDS} (4 lines on the PDF).")
    # Only the company's first distinctive word ("Acme" in "Acme Analytics AG"): later words
    # are often ordinary nouns ("Law", "Economics") a summary may legitimately use.
    tokens = [w for w in re.findall(r"[A-Za-z][A-Za-z&.-]{1,}", company or "") if w.lower() not in _COMPANY_STOPWORDS]
    if tokens and re.search(rf"\b{re.escape(tokens[0])}\b", summary, re.I):
        problems.append(f"Summary names the target company ({tokens[0]}); describe experience and contribution instead.")
    return problems


def _skill_group_count(draft: str) -> int | None:
    """Number of '- **Category:** ...' lines under '## Technical Skills', or None if absent."""
    m = re.search(r"^## Technical Skills\s*$(.*?)(?=^## |\Z)", draft, re.M | re.S)
    if not m:
        return None
    return len(re.findall(r"^\s*-\s+\*\*[^*]+\*\*", m.group(1), re.M))


def _previous_draft_text(state: CVDraftState) -> str:
    if state.attempt_count == 0:
        return state.seed_draft or "(none -- this is the first draft)"
    return state.draft_markdown or "(none)"


def draft_cv_node(state: CVDraftState) -> dict:
    prompt = _load_prompt("cv/draft").format(
        cv_template=cvpc.load_cv_template(),
        projects=pc.load_projects_for_cv(),
        coursework=pc.load_coursework_for_cv(),
        framing=state.framing,
        target_note=state.target_note,
        job_title=state.job_title,
        job_company=state.job_company,
        job_location=state.job_location or "(not specified)",
        job_level=state.job_level or "(not specified)",
        job_description=_truncate(state.job_description),
        previous_draft=_previous_draft_text(state),
        previous_feedback=_format_previous_feedback(state),
    )
    parsed, log = _call("deep", prompt, CVDraftOutput, provider="anthropic")
    return {
        "draft_markdown": parsed.draft_markdown,
        "attempt_count": state.attempt_count + 1,
        "node_logs": [log],
    }


def critique_cv_node(state: CVDraftState) -> dict:
    prompt = _load_prompt("cv/critique").format(
        target_note=state.target_note,
        cv_template=cvpc.load_cv_template(),
        projects=pc.load_projects_for_cv(),
        coursework=pc.load_coursework_for_cv(),
        job_title=state.job_title,
        job_company=state.job_company,
        job_description=_truncate(state.job_description),
        draft_markdown=state.draft_markdown,
    )
    parsed, log = _call("critique", prompt, CVCritique, provider="anthropic")

    # Deterministic backstop:
    # don't fully trust the LLM's own verdict against its own scores, since
    # a model's verdict can disagree with its own scores.
    # Second backstop, the other direction: the critique has twice accused an
    # honest draft of containing tools that appeared only in the job posting
    # (e.g. PyTorch/Hugging Face on 2026-09-29). Only fabrications backed by a
    # quote that literally exists in the draft count; with none, honesty can't
    # be scored below 4 -- missing job requirements are a relevance problem.
    honesty = parsed.honesty_score
    if honesty < 4 and not _verified_quotes(parsed.fabrication_quotes, state.draft_markdown or ""):
        honesty = 4

    verdict = parsed.verdict
    if verdict == "approve" and (honesty < 4 or parsed.relevance_score < 4):
        verdict = "revise"

    # Third/fourth backstops: summary length + no company name, and Technical Skills
    # must be 3-5 coherent groups. Counted
    # deterministically because the critique kept approving 8-9 categories.
    feedback = parsed.overall_feedback
    summary_problems = _summary_problems(state.draft_markdown or "", state.job_company)
    if summary_problems:
        verdict = "revise"
        feedback = " ".join(summary_problems) + " " + (feedback or "")
    n_groups = _skill_group_count(state.draft_markdown or "")
    if n_groups is not None and not MIN_SKILL_GROUPS <= n_groups <= MAX_SKILL_GROUPS:
        verdict = "revise"
        feedback = (
            f"Technical Skills has {n_groups} categories; use {MIN_SKILL_GROUPS}-{MAX_SKILL_GROUPS}. "
            "Merge closely related groups and drop minor or redundant items. " + (feedback or "")
        )

    return {
        "verdict": verdict,
        "relevance_score": parsed.relevance_score,
        "honesty_score": honesty,
        "impact_score": parsed.impact_score,
        "clarity_score": parsed.clarity_score,
        "keyword_alignment_score": parsed.keyword_alignment_score,
        "overall_feedback": feedback,
        "unresolved_gaps": parsed.unresolved_gaps,
        "node_logs": [log],
    }
