"""Pydantic schemas for pipeline state and structured LLM outputs.

Every LLM node returns one of these schemas via with_structured_output --
no free-text parsing anywhere in the pipeline.
"""
import operator
import re
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def _coerce_str_list(v):
    """Anthropic's tool-calling occasionally emits a list[str] field as
    '<item>...</item>'-wrapped text instead of a JSON array when there's a
    lot to report (observed on CVCritique.unresolved_gaps with 5+ items) --
    Pydantic then hard-fails validation instead of coercing it. Recover the
    list rather than crash the whole graph run over a formatting quirk."""
    if isinstance(v, str):
        items = re.findall(r"<item>(.*?)</item>", v, re.DOTALL)
        if items:
            return [item.strip() for item in items]
        return [v.strip()] if v.strip() else []
    return v


class NodeLog(BaseModel):
    node: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


class FilterGateResult(BaseModel):
    decision: Literal["keep", "exclude", "flag"]
    reasons: list[str] = Field(
        default_factory=list,
        description="Short reasons citing the specific filter rule(s) that applied. Empty if 'keep' with no concerns.",
    )

    _coerce_reasons = field_validator("reasons", mode="before")(_coerce_str_list)


class ThemeClassification(BaseModel):
    theme: Literal["1", "2", "3a", "3b", "4", "none"]
    rationale: str = Field(description="One sentence on why this theme, grounded in the job's actual content.")


class MatchScore(BaseModel):
    match_level: Literal["strong", "good", "moderate", "stretch"]
    rationale: str = Field(description="2-3 sentences citing specific evidence from the candidate's profile.")
    target_lane: Literal["part-time-now", "thesis", "internship-2027", "full-time-2027", "unclear"]


class GapExtraction(BaseModel):
    gaps: list[str] = Field(
        default_factory=list,
        description="Specific named gaps, e.g. 'wants Kubernetes: not in profile'. Empty if no material gaps.",
    )

    _coerce_gaps = field_validator("gaps", mode="before")(_coerce_str_list)


class ExtractedJobFields(BaseModel):
    title: str = Field(description="The job title. Empty string if genuinely not determinable from the text.")
    company: str = Field(description="The hiring company's name. Empty string if genuinely not determinable.")


class ExtractedJobPosting(BaseModel):
    title: str = Field(description="The job title. Empty string if genuinely not determinable.")
    company: str = Field(description="The hiring company's name. Empty string if genuinely not determinable.")
    location: str = Field(description="City/region if stated, e.g. 'Zurich' or 'Zurich (hybrid)'. Empty string if not stated.")
    description: str = Field(
        description="The actual job posting content (role, responsibilities, requirements) with page "
        "chrome -- nav links, cookie banners, unrelated 'similar jobs' listings, footer text -- removed. "
        "Keep the real content close to verbatim, don't summarize it."
    )


class JobBlurb(BaseModel):
    blurb: str = Field(
        description="One punchy sentence (~12-25 words) summarizing what this job actually is, for a card view."
    )


class DescriptionBreakdown(BaseModel):
    about_the_role: str = Field(description="1-3 sentences on what the role/team actually does.")
    key_responsibilities: list[str] = Field(default_factory=list)
    requirements_skills: list[str] = Field(default_factory=list)
    nice_to_have: list[str] = Field(default_factory=list)


class CVDraftOutput(BaseModel):
    draft_markdown: str = Field(description="The complete tailored CV, in Markdown, ready to export as-is.")


class CVCritique(BaseModel):
    relevance_score: int = Field(
        description="1-5: how well the draft's selected content maps to this specific job's stated requirements."
    )
    honesty_score: int = Field(
        description="1-5: how fully every claim in the draft is supported by the ground-truth profile, with no invention."
    )
    impact_score: int = Field(
        description="1-5: how concretely bullets show scope and outcome versus vague duties."
    )
    clarity_score: int = Field(
        description="1-5: readability, concision, consistent formatting, appropriate CV length."
    )
    keyword_alignment_score: int = Field(
        description="1-5: coverage of the job posting's named skills/tools, using only ones truthfully evidenced in the ground truth."
    )
    verdict: Literal["approve", "revise"] = Field(
        description="'approve' only if honesty_score and relevance_score are both >=4 and there is no fabrication; 'revise' otherwise."
    )
    overall_feedback: str = Field(
        description="2-4 sentences: the single most important thing to fix next, as if a recruiter were giving one piece of feedback."
    )
    unresolved_gaps: list[str] = Field(
        default_factory=list,
        description="Specific things the job wants that the draft could not truthfully support from the ground-truth profile, e.g. 'wants Tableau: not found in profile'.",
    )

    fabrication_quotes: list[str] = Field(
        default_factory=list,
        description="For every fabricated or altered detail you found, the exact verbatim text copied from the draft. Empty if you found none. Never list something the job wants but the draft doesn't claim.",
    )

    _coerce_gaps = field_validator("unresolved_gaps", mode="before")(_coerce_str_list)
    _coerce_quotes = field_validator("fabrication_quotes", mode="before")(_coerce_str_list)


class CVDraftState(BaseModel):
    # input
    job_id: str
    job_title: str
    job_company: str
    job_location: Optional[str] = None
    job_level: Optional[str] = None
    job_description: Optional[str] = None
    theme: str  # "1" | "2" | "3a" | "3b" | "4" -- caller guarantees a real theme, never None/"none"

    # seed context for a "regenerate" run only; both None for a fresh "Prepare CV" run
    seed_draft: Optional[str] = None
    seed_notes: Optional[str] = None

    # loop state -- draft_cv_node increments attempt_count on every call
    attempt_count: int = 0
    draft_markdown: Optional[str] = None

    # critique_cv_node output, overwritten each iteration (only the latest matters)
    verdict: Optional[str] = None
    relevance_score: Optional[int] = None
    honesty_score: Optional[int] = None
    impact_score: Optional[int] = None
    clarity_score: Optional[int] = None
    keyword_alignment_score: Optional[int] = None
    overall_feedback: Optional[str] = None
    unresolved_gaps: list[str] = Field(default_factory=list)

    node_logs: Annotated[list[NodeLog], operator.add] = Field(default_factory=list)


class PipelineState(BaseModel):
    # input
    job_id: str
    title: str
    company: str
    location: Optional[str] = None
    description: Optional[str] = None
    level: Optional[str] = None
    forced_theme: Optional[str] = None  # set from Job.forced_theme; bypasses classify_theme's LLM call
    manual: bool = False  # hand-picked job: exclude rules become warnings (flag) instead of stopping screening

    # generate_blurb (runs unconditionally, before the filter_gate short-circuit)
    blurb: Optional[str] = None

    # filter_gate
    decision: Optional[str] = None
    filter_reasons: list[str] = Field(default_factory=list)

    # classify_theme
    theme: Optional[str] = None
    theme_rationale: Optional[str] = None

    # score_match
    match_level: Optional[str] = None
    match_rationale: Optional[str] = None
    target_lane: Optional[str] = None

    # extract_gaps
    gaps: list[str] = Field(default_factory=list)

    # observability -- Annotated with operator.add so each node's returned
    # list gets appended to, not overwritten (this is the LangGraph reducer pattern)
    node_logs: Annotated[list[NodeLog], operator.add] = Field(default_factory=list)
