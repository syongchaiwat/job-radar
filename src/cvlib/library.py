"""Build, version and apply archetype CVs.

- market_brief(): the archetype as a "posting" for the existing draft/critique loop
- generate(): runs the loop (all CV guardrails apply) and stores a CVVersion
- status(): outdated detection (new market-data jobs since the build, profile changed)
- cv_for_job() / apply_lane_slot(): which CV a job uses, plus its lane sentence
"""
import hashlib
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from src.db import Archetype, ArchetypeSet, CVVersion, Job, JobArchetype, RoleCard
from src.market.stats import market_overview
from src.pipeline import profile_context as pc
from src.pipeline.cv_export import CV_DRAFTS_DIR, REPO_ROOT
from src.pipeline.schemas import CVDraftState

MANUAL_EDIT = "manual-edit"
TEMPLATE = REPO_ROOT / "cv_profile" / "cv_template.md"

# Fallback lane sentences when a job has no lane from lanes.md yet. Keyed by the
# role card's employment_type; full-time gets none.
DEFAULT_LANE_SLOTS = {
    "working_student": "Available part-time during the semester.",
    "part_time": "Available part-time during the semester.",
    "internship": "Available for an internship.",
    "thesis": "Open to a master's thesis collaboration.",
}


def _active_set(session: Session) -> ArchetypeSet | None:
    return session.exec(select(ArchetypeSet).where(ArchetypeSet.status == "active")).first()


def profile_hash() -> str:
    parts = [pc.load_projects(), pc.load_coursework(), TEMPLATE.read_text() if TEMPLATE.exists() else ""]
    return hashlib.sha1("\n".join(parts).encode()).hexdigest()


def _row_for(session: Session, archetype_id: int, refresh_evidence: bool = False) -> dict | None:
    return next((r for r in market_overview(session, refresh_evidence=refresh_evidence)["archetypes"] if r["archetype"].id == archetype_id), None)


def market_hash(row: dict) -> str:
    ids = sorted(job.id for job, _ in row["jobs"])
    skills = sorted((d["skill"], d["jobs"]) for d in row["demand"])
    return hashlib.sha1(json.dumps([ids, skills]).encode()).hexdigest()


def market_brief(row: dict) -> str:
    a: Archetype = row["archetype"]
    rnd = random.Random(a.id)
    resp = []
    for _, card in row["jobs"]:
        resp.extend(json.loads(card.responsibilities or "[]"))
    rnd.shuffle(resp)
    seen, sample = set(), []
    for r in resp:
        key = r.lower()[:60]
        if key not in seen:
            seen.add(key)
            sample.append(r)
        if len(sample) >= 15:
            break
    demand = "\n".join(
        f"- {d['skill']}: {round(d['share'] * 100)}% of postings ({d['required']} required, {d['nice']} nice-to-have)"
        for d in row["demand"][:25]
    )
    return f"""MARKET BRIEF for the archetype "{a.name}" ({row['n']} postings).

What these jobs do: {a.definition}
Include: {a.include_criteria or '-'}

Most requested skills:
{demand}

Typical responsibilities (sampled across postings):
{chr(10).join('- ' + r for r in sample)}

Levels: {', '.join(f'{k} {v}' for k, v in row['levels'])}
Employment types: {', '.join(f"{k.replace('_', ' ')} {v}" for k, v in row['lanes'])}
Domains: {', '.join(f'{k} ({v})' for k, v in row['domains'])}"""


def framing(row: dict) -> str:
    strengths = ", ".join(f"{d['skill']} ({round(d['share'] * 100)}%)" for d in row["strengths"]) or "-"
    gaps = ", ".join(f"{d['skill']} ({round(d['share'] * 100)}%)" for d in row["gaps"]) or "-"
    return f"""# Archetype framing: {row['archetype'].name}

Lead with the candidate's strengths this market asks for most: {strengths}.

Gaps (asked for, but the candidate has no evidence: never claim these, they belong in unresolved_gaps): {gaps}."""


TARGET_NOTE = (
    "**Note:** the posting below is a MARKET BRIEF, not a single job: it aggregates many postings of one kind of work "
    "(an archetype). Write the CV for the archetype as a whole: the strongest truthful proof of the skills these jobs "
    "ask for most. There is no company; never mention any company or role you are applying to. The CV will be reused "
    "for every job in the archetype, so do not narrow it to one employer's wording."
)


def _next_file(archetype: Archetype, cv: CVVersion, session: Session) -> str:
    CV_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    n = len(session.exec(select(CVVersion).where(CVVersion.archetype_slug == archetype.slug)).all()) + 1
    path = CV_DRAFTS_DIR / f"archetype-{archetype.slug}_v{n}.md"
    path.write_text(cv.draft_markdown)
    return str(path.relative_to(REPO_ROOT))


def generate(session: Session, archetype_id: int, seed: CVVersion | None = None) -> CVVersion:
    from src.pipeline.cv_run import GRAPH, _strip_template_metadata

    archetype = session.get(Archetype, archetype_id)
    row = _row_for(session, archetype_id, refresh_evidence=True)
    if archetype is None or row is None:
        raise ValueError("Unknown archetype")
    if row["n"] == 0:
        raise ValueError("This archetype has no market-data jobs yet, so there is no market brief to build a CV from.")
    state = CVDraftState(
        job_id=f"archetype-{archetype.slug}", job_title=archetype.name, job_company="",
        job_location="Switzerland", job_level=", ".join(k for k, _ in row["levels"][:2]),
        job_description=market_brief(row), theme=archetype.slug,
        theme_profile_text=framing(row), target_note=TARGET_NOTE,
        seed_draft=seed.draft_markdown if seed else None,
        seed_notes=(f"Previous version's feedback: {seed.overall_feedback}" if seed and seed.overall_feedback else None),
    )
    result = GRAPH.invoke(state.model_dump())
    final = CVDraftState.model_validate(result)
    cv = CVVersion(
        archetype_id=archetype.id, archetype_slug=archetype.slug,
        draft_markdown=_strip_template_metadata(final.draft_markdown or ""),
        attempt_count=final.attempt_count, verdict=final.verdict or "revise",
        relevance_score=final.relevance_score, honesty_score=final.honesty_score, impact_score=final.impact_score,
        clarity_score=final.clarity_score, keyword_alignment_score=final.keyword_alignment_score,
        overall_feedback=final.overall_feedback, unresolved_gaps=json.dumps(final.unresolved_gaps),
        source_job_ids=json.dumps(sorted(job.id for job, _ in row["jobs"])),
        market_hash=market_hash(row), profile_hash=profile_hash(),
        model_used=",".join(sorted({log.model for log in final.node_logs})) or None,
        tokens=sum(log.input_tokens + log.output_tokens for log in final.node_logs),
        latency_ms=sum(log.latency_ms for log in final.node_logs),
    )
    cv.file_path = _next_file(archetype, cv, session)
    session.add(cv)
    session.commit()
    session.refresh(cv)
    return cv


def save_edit(session: Session, base: CVVersion, markdown: str) -> CVVersion:
    archetype = session.get(Archetype, base.archetype_id)
    cv = CVVersion(**{k: getattr(base, k) for k in (
        "archetype_id", "archetype_slug", "attempt_count", "verdict", "relevance_score", "honesty_score",
        "impact_score", "clarity_score", "keyword_alignment_score", "overall_feedback", "unresolved_gaps",
        "source_job_ids", "market_hash", "profile_hash")})
    cv.draft_markdown, cv.model_used, cv.tokens, cv.latency_ms = markdown, MANUAL_EDIT, 0, 0
    cv.created_at = datetime.now(timezone.utc)
    cv.file_path = _next_file(archetype, cv, session)
    session.add(cv)
    session.commit()
    session.refresh(cv)
    return cv


def versions(session: Session, archetype_slug: str) -> list[CVVersion]:
    return session.exec(select(CVVersion).where(CVVersion.archetype_slug == archetype_slug).order_by(CVVersion.id)).all()


def status(session: Session, cv: CVVersion | None, row: dict | None) -> dict:
    """Outdated reasons for the latest CV of an archetype."""
    if cv is None or row is None:
        return {"outdated": False, "reasons": []}
    reasons = []
    built_from = set(json.loads(cv.source_job_ids or "[]"))
    now = {job.id for job, _ in row["jobs"]}
    new, gone = len(now - built_from), len(built_from - now)
    if new:
        reasons.append(f"{new} new market-data job{'s' if new != 1 else ''} since this CV was built")
    if gone:
        reasons.append(f"{gone} job{'s' if gone != 1 else ''} left the archetype")
    if not new and not gone and cv.market_hash != market_hash(row):
        reasons.append("skill demand changed")
    if cv.profile_hash != profile_hash():
        reasons.append("your profile changed (projects, coursework or CV template)")
    return {"outdated": bool(reasons), "reasons": reasons}


def primary_archetype(session: Session, job_id: str) -> Archetype | None:
    aset = _active_set(session)
    if aset is None:
        return None
    r = session.exec(select(JobArchetype).where(JobArchetype.job_id == job_id, JobArchetype.set_version == aset.version,
                                                JobArchetype.role == "primary")).first()
    return session.get(Archetype, r.archetype_id) if r else None


def cv_for_job(session: Session, job: Job) -> CVVersion | None:
    """The job's chosen CV, else the latest CV of its archetype (matched by slug, so it survives set versions)."""
    if job.cv_version_id:
        cv = session.get(CVVersion, job.cv_version_id)
        if cv:
            return cv
    a = primary_archetype(session, job.id)
    if a is None:
        return None
    vs = versions(session, a.slug)
    return vs[-1] if vs else None


def lane_slot(session: Session, job: Job) -> str:
    """The job's lane sentence from lanes.md; falls back to a default by employment type."""
    from src.lanes import lane_by_key

    lane = lane_by_key(job.lane)
    if lane is not None:
        return lane.slot
    card = session.get(RoleCard, job.id)
    et = json.loads(card.lane_signals or "{}").get("employment_type") if card else None
    return DEFAULT_LANE_SLOTS.get(et or "", "")


def apply_lane_slot(markdown: str, slot: str) -> str:
    """Append the lane sentence to the end of the Summary paragraph."""
    m = re.search(r"^## Summary\s*\n+", markdown, re.M)
    if not slot or not m:
        return markdown
    start = m.end()
    end = markdown.find("\n\n", start)
    end = len(markdown) if end == -1 else end
    para = markdown[start:end].rstrip()
    if slot in para:
        return markdown
    return markdown[:start] + para + " " + slot + markdown[start + len(para):]
