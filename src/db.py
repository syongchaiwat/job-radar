"""SQLite schema and engine for job-radar."""
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlmodel import Field, SQLModel, create_engine, Session

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = "data/job_radar.db"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(SQLModel, table=True):
    """A single posting, deduped by id (hash of URL)."""

    id: str = Field(primary_key=True)
    source: str  # "seed" | "adzuna" | "jsearch" | "manual"
    url: str
    company: str
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    level: Optional[str] = None  # raw seniority/workload text
    posted_at: Optional[datetime] = None
    first_seen: datetime = Field(default_factory=_utcnow)
    theme_hint: Optional[str] = None  # which theme's keyword search surfaced this job (adzuna/jsearch only)
    forced_theme: Optional[str] = None  # user override: screening skips classify_theme and uses this instead
    description_breakdown: Optional[str] = None  # JSON-encoded DescriptionBreakdown, computed lazily on first Job Detail view
    description_breakdown_computed_at: Optional[datetime] = None
    cv_version_id: Optional[int] = None  # CV library choice for this job; None = latest CV of its archetype
    market_data: bool = False  # user switch: this posting shapes archetypes and market stats (independent of application status)


class GroundTruth(SQLModel, table=True):
    """Hand-labeled theme/fit, one row per job (latest label wins). Eval
    reference, not app output. Not just the original 24 seed jobs forever --
    source/created_at track provenance so future corrections made while
    using the real dashboard (Phase 4) can land here too, generically."""

    job_id: str = Field(primary_key=True, foreign_key="job.id")
    theme_raw: str
    theme_code: str  # normalized: "1" | "2" | "3a" | "3b" | "4" | "none"
    fit_raw: str
    source: str = Field(default="seed")  # e.g. "seed_2026-08-12" | "user_correction"
    created_at: Optional[datetime] = None  # None for rows migrated in before this field existed


class Screening(SQLModel, table=True):
    """LangGraph pipeline output for a job. One row per screening run."""

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="job.id")
    decision: str  # "keep" | "exclude" | "flag"
    filter_reasons: str = "[]"  # JSON-encoded list[str]
    theme: Optional[str] = None
    theme_rationale: Optional[str] = None
    blurb: Optional[str] = None  # one-sentence card summary from generate_blurb_node
    match_level: Optional[str] = None  # "strong" | "good" | "moderate" | "stretch" | None
    match_rationale: Optional[str] = None
    gaps: str = "[]"  # JSON-encoded list[str]
    target_lane: Optional[str] = None
    model_used: Optional[str] = None
    tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    created_at: datetime = Field(default_factory=_utcnow)


class Tracking(SQLModel, table=True):
    """Application status, one row per job."""

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="job.id", unique=True)
    status: str = "new"  # new | shortlist | applied | in-process | offer | rejected | ignored
    applied_at: Optional[datetime] = None
    notes: Optional[str] = None
    updated_at: datetime = Field(default_factory=_utcnow)


class CVDraft(SQLModel, table=True):
    """CV draft/critique pipeline output for a job. One row per generation
    run (fresh 'Prepare CV' or seeded 'Regenerate') -- job_id has no unique
    constraint, mirroring Screening, so history is preserved and a
    regenerate can always seed from the latest row for that job."""

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="job.id")
    theme: str
    draft_markdown: str
    attempt_count: int
    verdict: str  # "approve" | "revise" -- "revise" + attempt_count>=MAX_ATTEMPTS means it hit the ceiling unresolved
    relevance_score: Optional[int] = None
    honesty_score: Optional[int] = None
    impact_score: Optional[int] = None
    clarity_score: Optional[int] = None
    keyword_alignment_score: Optional[int] = None
    overall_feedback: Optional[str] = None
    unresolved_gaps: str = "[]"  # JSON-encoded list[str], matches Screening.gaps convention
    is_regenerate: bool = False
    file_path: Optional[str] = None  # relative path under cv_drafts/
    model_used: Optional[str] = None
    tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    created_at: datetime = Field(default_factory=_utcnow)


class RoleCard(SQLModel, table=True):
    """Normalized English summary of a posting: what every comparison (archetype
    assignment, clustering, market stats) runs on instead of the raw text.
    prompt_version + model let a rework refresh only outdated cards."""

    job_id: str = Field(primary_key=True, foreign_key="job.id")
    prompt_version: str
    model: str
    title_normalized: str
    summary: str
    responsibilities: str = "[]"  # JSON list[str]
    domain: Optional[str] = None
    level: str = "unspecified"
    languages_required: str = "[]"  # JSON list[str]
    lane_signals: str = "{}"  # JSON LaneSignals (raw; lanes themselves come later)
    information_quality: str = "partial"  # rich | partial | thin
    language_ok: bool = True  # False if the card doesn't read as English
    created_at: datetime = Field(default_factory=_utcnow)


class Skill(SQLModel, table=True):
    """Canonical skill in the skill dictionary. New names proposed during
    extraction start as 'pending' until approved (or merged into another)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    category: str = "other"
    status: str = "pending"  # pending | approved
    created_at: datetime = Field(default_factory=_utcnow)


class SkillAlias(SQLModel, table=True):
    """Alternative spelling -> canonical skill (e.g. 'large language models' -> LLM).
    Stored lowercase; merging skills turns the merged name into an alias."""

    alias: str = Field(primary_key=True)
    skill_id: int = Field(foreign_key="skill.id")


class JobSkill(SQLModel, table=True):
    job_id: str = Field(primary_key=True, foreign_key="job.id")
    skill_id: int = Field(primary_key=True, foreign_key="skill.id")
    importance: str = "required"  # required | nice_to_have
    raw_term: Optional[str] = None


class Embedding(SQLModel, table=True):
    """Dense vector of a job's role card. Recomputed only when the card text
    (role_card_hash) or the embedding model changes."""

    job_id: str = Field(primary_key=True, foreign_key="job.id")
    model: str
    role_card_hash: str
    dim: int
    vector: bytes  # float32, L2-normalized
    created_at: datetime = Field(default_factory=_utcnow)


class ArchetypeSet(SQLModel, table=True):
    """A confirmed set of archetypes. Exactly one is active; older ones stay for history.
    Version 0 is seeded from the legacy hand-written themes."""

    version: int = Field(primary_key=True)
    status: str = "active"  # active | superseded
    notes: Optional[str] = None
    params: str = "{}"  # JSON: calibrated assignment thresholds etc.
    created_at: datetime = Field(default_factory=_utcnow)


class Archetype(SQLModel, table=True):
    """A kind of work, shared across lanes, learned from market-data jobs."""

    id: Optional[int] = Field(default=None, primary_key=True)
    set_version: int = Field(foreign_key="archetypeset.version")
    slug: str
    name: str
    definition: str
    include_criteria: str = ""
    exclude_criteria: str = ""
    defining_skills: str = "[]"  # JSON list[str]
    maps_from: str = "[]"  # JSON list[int]: archetype ids in the previous set this one continues
    legacy_theme: Optional[str] = None  # set v0 only: the theme code it came from
    created_at: datetime = Field(default_factory=_utcnow)


class JobArchetype(SQLModel, table=True):
    """Assignment of a job to an archetype within one set (primary, optionally a secondary)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    job_id: str = Field(foreign_key="job.id", index=True)
    set_version: int = Field(foreign_key="archetypeset.version")
    archetype_id: int = Field(foreign_key="archetype.id")
    role: str = "primary"  # primary | secondary
    method: str = "embedding"  # embedding | llm | user | rework | legacy
    score: Optional[float] = None
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)


class ClassifyRun(SQLModel, table=True):
    """One archetype rework: runs in the background, produces a draft proposal
    (JSON) that you edit on the Classify page, then confirm into a new set."""

    id: Optional[int] = Field(default=None, primary_key=True)
    status: str = "running"  # running | draft | confirmed | discarded | failed
    progress: str = ""
    error: Optional[str] = None
    base_version: Optional[int] = None  # the active set when the run started
    proposal: str = "{}"  # JSON, see src/archetypes/rework.py
    cost_tokens: int = 0
    created_at: datetime = Field(default_factory=_utcnow)
    finished_at: Optional[datetime] = None


class ProfileTerm(SQLModel, table=True):
    """A tool/skill term from your profile (projects.md Tools, CV template skills)
    mapped to canonical dictionary skills. Cached per term; only new terms are mapped."""

    term: str = Field(primary_key=True)  # lowercase as written
    skill_ids: str = "[]"  # JSON list[int]; empty = no dictionary equivalent
    method: str = "exact"  # exact | alias | stripped | llm
    created_at: datetime = Field(default_factory=_utcnow)


class MarketSuggestion(SQLModel, table=True):
    """LLM-suggested next steps to close an archetype's top gaps (on demand)."""

    archetype_id: int = Field(primary_key=True, foreign_key="archetype.id")
    suggestions: str = "[]"  # JSON list[{title, why, how}]
    created_at: datetime = Field(default_factory=_utcnow)


class MarketTodo(SQLModel, table=True):
    """Your own to-dos per archetype; keyed by slug so they survive set versions."""

    id: Optional[int] = Field(default=None, primary_key=True)
    archetype_slug: str = Field(index=True)
    text: str
    done: bool = False
    created_at: datetime = Field(default_factory=_utcnow)


class CVVersion(SQLModel, table=True):
    """CV library: one CV per archetype (versioned), built from the archetype's
    market brief and reused across its jobs. Hashes drive the 'outdated' badge."""

    id: Optional[int] = Field(default=None, primary_key=True)
    archetype_id: int = Field(foreign_key="archetype.id", index=True)
    archetype_slug: str = Field(index=True)
    draft_markdown: str
    attempt_count: int = 0
    verdict: str = "revise"
    relevance_score: Optional[int] = None
    honesty_score: Optional[int] = None
    impact_score: Optional[int] = None
    clarity_score: Optional[int] = None
    keyword_alignment_score: Optional[int] = None
    overall_feedback: Optional[str] = None
    unresolved_gaps: str = "[]"
    source_job_ids: str = "[]"  # market-data members the brief was built from
    market_hash: str = ""
    profile_hash: str = ""
    model_used: Optional[str] = None  # "manual-edit" for hand edits
    tokens: Optional[int] = None
    latency_ms: Optional[float] = None
    file_path: Optional[str] = None
    created_at: datetime = Field(default_factory=_utcnow)


def get_engine(db_path: Optional[str] = None):
    path = Path(db_path or os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH))
    if not path.is_absolute():
        # Anchor relative paths to the repo root, not the process's CWD --
        # a bare relative path breaks the moment something launches this
        # from an unexpected working directory (e.g. uvicorn via --app-dir,
        # which fixes Python's module resolution but not the process CWD).
        path = REPO_ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return create_engine(f"sqlite:///{path}")


# Columns added to existing tables after they were first created. create_all()
# only creates missing tables, so older databases get these via ALTER TABLE.
_ADDED_COLUMNS = {
    "job": {
        "forced_theme": "VARCHAR",
        "market_data": "BOOLEAN NOT NULL DEFAULT 0",
        "cv_version_id": "INTEGER",
    },
}


def _migrate(engine) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def init_db(engine=None):
    engine = engine or get_engine()
    SQLModel.metadata.create_all(engine)
    _migrate(engine)
    return engine


def get_session(engine=None) -> Session:
    engine = engine or get_engine()
    return Session(engine)
