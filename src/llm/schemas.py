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


class MatchScore(BaseModel):
    match_level: Literal["strong", "good", "moderate", "stretch"]
    rationale: str = Field(description="2-3 sentences citing specific evidence from the candidate's profile.")


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
    archetype_slug: str  # the archetype this CV is framed for
    framing: str  # market-derived framing for that archetype (strengths, gaps, most-asked skills)
    target_note: str = ""  # archetype CVs: tells both nodes the "posting" is a market brief

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
    archetype: Optional[str] = None  # the job's archetype (name + definition), when it has one
    manual: bool = False  # hand-picked job: exclude rules become warnings (flag) instead of stopping screening

    # generate_blurb (runs unconditionally, before the filter_gate short-circuit)
    blurb: Optional[str] = None

    # filter_gate
    decision: Optional[str] = None
    filter_reasons: list[str] = Field(default_factory=list)

    # score_match
    match_level: Optional[str] = None
    match_rationale: Optional[str] = None

    # extract_gaps
    gaps: list[str] = Field(default_factory=list)

    # observability -- Annotated with operator.add so each node's returned
    # list gets appended to, not overwritten (this is the LangGraph reducer pattern)
    node_logs: Annotated[list[NodeLog], operator.add] = Field(default_factory=list)


# --- Role cards (pipeline revamp, Phase 1) -----------------------------------

SkillCategory = Literal[
    "programming_language", "ml_method", "statistics", "ml_framework", "llm_genai",
    "data_engineering", "database", "cloud_platform", "mlops_devops", "visualization_bi",
    "software_engineering", "domain_knowledge", "methodology", "other",
]


class ExtractedSkill(BaseModel):
    name: str = Field(
        description="Canonical skill name in English. If the concept is already in the known-skills list, copy that "
        "exact name; otherwise a short, conventional name (e.g. 'PyTorch', 'LLM', 'A/B testing', 'Kubernetes')."
    )
    category: SkillCategory
    importance: Literal["required", "nice_to_have"]
    raw_term: str = Field(description="The term as it appears in the posting (any language).")

    @field_validator("category", mode="before")
    @classmethod
    def _unknown_category_is_other(cls, v):
        return v if v in SkillCategory.__args__ else "other"


class LaneSignals(BaseModel):
    employment_type: Literal[
        "working_student", "internship", "thesis", "full_time", "part_time", "contract", "unclear"
    ]
    duration_months: Optional[int] = Field(default=None, description="Stated duration in months, if any.")
    workload_min_pct: Optional[int] = Field(default=None, description="Lower bound of stated workload in percent, e.g. 40 for '40-60%'.")
    workload_max_pct: Optional[int] = Field(default=None, description="Upper bound of stated workload in percent.")
    start_date: Optional[str] = Field(default=None, description="Stated start date or period as written, e.g. 'January 2027', 'asap'.")
    mentions_thesis: bool = Field(description="True if the posting mentions writing a thesis with the company.")


class RoleCardExtraction(BaseModel):
    title_normalized: str = Field(description="Job title in English without company name, gender markers or workload, e.g. 'Machine Learning Engineer'.")
    summary: str = Field(description="2-3 English sentences on what the role actually does day to day, without company marketing.")
    responsibilities: list[str] = Field(description="3-6 short English phrases, the core responsibilities.")
    skills: list[ExtractedSkill] = Field(description="Specific skills, tools and methods asked for. Not soft skills like 'team player'.")
    domain: str = Field(description="Industry or business domain in a few English words, e.g. 'payments fintech', 'reinsurance'.")
    level: Literal["intern", "student", "junior", "mid", "senior", "lead", "unspecified"]
    languages_required: list[str] = Field(default_factory=list, description="Spoken languages with level as stated, e.g. 'German (fluent)', 'English (C1)'.")
    lane_signals: LaneSignals
    information_quality: Literal["rich", "partial", "thin"] = Field(
        description="rich = detailed responsibilities and requirements; partial = some detail; thin = a short or vague posting."
    )

    _coerce_resp = field_validator("responsibilities", "languages_required", mode="before")(_coerce_str_list)


# --- Archetypes (pipeline revamp, Phase 2) -----------------------------------

class ArchetypeAdjudication(BaseModel):
    archetype: str = Field(description="The key of the best-fitting candidate archetype, or 'none' if none of them fits.")
    secondary: Optional[str] = Field(default=None, description="Key of a second archetype the job also clearly fits, if any.")
    confidence: float = Field(description="0-1: how confident you are in the choice.")
    rationale: str = Field(description="One sentence grounded in the job's responsibilities and skills.")


class ArchetypeDef(BaseModel):
    name: str = Field(description="Short name of the kind of work, e.g. 'LLM & agent engineering'.")
    definition: str = Field(description="1-2 sentences: what jobs in this archetype actually do.")
    include: str = Field(description="What clearly belongs here (signals in a posting).")
    exclude: str = Field(description="Near misses that belong elsewhere, and where.")
    defining_skills: list[str] = Field(description="5-10 skills most characteristic of this archetype (use the skill names from the cards).")

    _coerce_skills = field_validator("defining_skills", mode="before")(_coerce_str_list)


class Taxonomy(BaseModel):
    archetypes: list[ArchetypeDef]
    changes: str = Field(default="", description="What changed versus the previous version and why (empty for the first batch).")


class JobLabel(BaseModel):
    job_id: str
    archetype: str = Field(description="Exact archetype name from the taxonomy, or 'none'.")
    confidence: float = Field(description="0-1")


class JobLabels(BaseModel):
    labels: list[JobLabel]


class FinalArchetype(ArchetypeDef):
    key: str = Field(description="Short lowercase slug, e.g. 'llm-engineering'.")
    maps_from: list[str] = Field(default_factory=list, description="Names of current archetypes this one continues (empty if new).")
    from_clusters: list[int] = Field(default_factory=list, description="Track 1 cluster ids this archetype draws on.")
    from_taxonomy: list[str] = Field(default_factory=list, description="Track 2 archetype names this archetype draws on.")


class Assignment(BaseModel):
    job_id: str
    archetype: str = Field(description="Final archetype key, or 'none'.")


class Reconciliation(BaseModel):
    archetypes: list[FinalArchetype]
    assignments: list[Assignment] = Field(description="Every job in the pool exactly once.")
    notes: str = Field(description="Merges, splits, retirements of current archetypes, and how disagreements between the tracks were resolved.")


class SplitNaming(BaseModel):
    parts: list[ArchetypeDef] = Field(description="One definition per group, in the order given.")


# --- Market layer (pipeline revamp, Phase 3) ---------------------------------

class TermMapping(BaseModel):
    term: str
    skills: list[str] = Field(default_factory=list, description="Exact canonical skill names this term is evidence for; empty if none.")


class TermMappings(BaseModel):
    mappings: list[TermMapping]


class NextStep(BaseModel):
    title: str = Field(description="Short imperative, e.g. 'Containerize job-radar and deploy it with Docker'.")
    why: str = Field(description="Which gaps it closes and how often the market asks for them.")
    how: str = Field(description="1-2 concrete sentences on how to do it, building on existing projects where possible.")


class NextSteps(BaseModel):
    steps: list[NextStep]


# --- Lanes and cover letters (pipeline revamp, Phase 5) -----------------------

class LaneJudgment(BaseModel):
    lane: str = Field(description="The key of the lane the job belongs to.")
    eligible: Literal["yes", "no", "unclear"] = Field(description="Does the job meet the lane's Eligible requirements?")
    eligibility_reasons: list[str] = Field(default_factory=list, description="Short reasons citing the posting; mention what is unknown.")
    value_score: float = Field(description="0-1: how well the job scores on the lane's Value criteria.")
    value_reasons: list[str] = Field(default_factory=list, description="One short reason per Value criterion that applies or clearly doesn't.")
    deadline: Optional[str] = Field(default=None, description="Application deadline as YYYY-MM-DD if the posting states one, else null.")

    _coerce = field_validator("eligibility_reasons", "value_reasons", mode="before")(_coerce_str_list)


class CoverLetterDraft(BaseModel):
    body_markdown: str = Field(description="The letter from the greeting to the sign-off, in Markdown paragraphs.")


class CoverLetterCritique(BaseModel):
    verdict: Literal["approve", "revise"]
    honesty_score: int = Field(description="1-5: every claim traceable to the CV or project database.")
    relevance_score: int = Field(description="1-5: addresses what this posting actually asks for.")
    specificity_score: int = Field(description="1-5: specific to this company and role, not generic.")
    tone_score: int = Field(description="1-5: plain, simple voice; simple who/what/why opening, then evidence; no hype or em dashes.")
    fabrication_quotes: list[str] = Field(default_factory=list, description="Verbatim text from the letter for every unsupported or altered claim.")
    feedback: str = Field(description="Concrete changes for the next draft.")

    _coerce = field_validator("fabrication_quotes", mode="before")(_coerce_str_list)
