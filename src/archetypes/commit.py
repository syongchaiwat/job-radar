"""Archetype sets: seed v0 from the legacy themes, confirm a rework proposal into
a new version, assign individual jobs, export generated notes to the vault."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from src.archetypes.assign import DEFAULT_THRESHOLDS, Profile, assign, build_profiles
from src.archetypes.features import load_jobs, skill_idf, top_skills
from src.db import Archetype, ArchetypeSet, ClassifyRun, GroundTruth, Job, JobArchetype, Screening
from src.pipeline import profile_context as pc

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _active(session: Session) -> ArchetypeSet | None:
    return session.exec(select(ArchetypeSet).where(ArchetypeSet.status == "active")).first()


def seed_v0(session: Session) -> ArchetypeSet | None:
    """Set v0 = the legacy hand-written themes, so assignment works before the first rework.
    Members come from your label, a pinned theme, or the latest screening's theme."""
    if session.exec(select(ArchetypeSet)).first() is not None:
        return None
    aset = ArchetypeSet(version=0, status="active", notes="Seeded from the legacy themes (profile/themes).")
    session.add(aset)
    session.flush()
    by_theme = {}
    for code in pc.THEME_FILES:
        text = pc.load_theme(code)
        name = (re.search(r"^name:\s*(.+)$", text, re.M) or [None, f"Theme {code}"])[1].strip()
        intro = re.search(r"^# [^\n]+\n\n(.+?)(?:\n\n|\Z)", text, re.M | re.S)
        kw = re.search(r"## Retrieval keywords\s*\n(.+)", text)
        a = Archetype(set_version=0, slug=f"theme-{code}", name=name, definition=intro.group(1).strip() if intro else name,
                      defining_skills=json.dumps([k.strip() for k in (kw.group(1).split(",") if kw else [])][:10]),
                      legacy_theme=code)
        session.add(a)
        session.flush()
        by_theme[code] = a
    latest = {}
    for sc in session.exec(select(Screening).order_by(Screening.id)).all():
        latest[sc.job_id] = sc
    for job in session.exec(select(Job)).all():
        gt = session.get(GroundTruth, job.id)
        theme = (gt.theme_code if gt and gt.source == "user_correction" else None) or job.forced_theme or (latest.get(job.id).theme if job.id in latest else None)
        if theme in by_theme:
            session.add(JobArchetype(job_id=job.id, set_version=0, archetype_id=by_theme[theme].id, method="legacy",
                                     rationale="from the legacy theme"))
    session.commit()
    return aset


def profiles_for_set(session: Session, version: int):
    """Profiles of a confirmed set; members = market-data jobs with a primary assignment."""
    archetypes = session.exec(select(Archetype).where(Archetype.set_version == version)).all()
    rows = session.exec(select(JobArchetype).where(JobArchetype.set_version == version, JobArchetype.role == "primary")).all()
    member_ids = {r.job_id for r in rows}
    jobs = {pj.job_id: pj for pj in load_jobs(session, list(member_ids), market_only=True)}
    pool_all = load_jobs(session, market_only=True)
    idf = skill_idf(pool_all or list(jobs.values()))
    by_arch: dict[int, list] = {}
    for r in rows:
        if r.job_id in jobs:
            by_arch.setdefault(r.archetype_id, []).append(jobs[r.job_id])
    profiles = build_profiles([
        Profile(key=str(a.id), name=a.name, definition=a.definition, include=a.include_criteria, exclude=a.exclude_criteria,
                defining_skills=json.loads(a.defining_skills or "[]"), members=by_arch.get(a.id, []))
        for a in archetypes
    ], idf)
    return profiles, idf


def assign_job(session: Session, job_id: str, use_llm: bool = True) -> JobArchetype | None:
    """Assign one job in the active set (unless you moved it by hand). Caller commits."""
    aset = _active(session)
    if aset is None:
        return None
    existing = session.exec(select(JobArchetype).where(JobArchetype.job_id == job_id, JobArchetype.set_version == aset.version)).all()
    if any(r.method == "user" for r in existing):
        return next(r for r in existing if r.role == "primary")
    jobs = load_jobs(session, [job_id])
    if not jobs:
        return None
    profiles, idf = profiles_for_set(session, aset.version)
    thresholds = json.loads(aset.params or "{}").get("thresholds") or DEFAULT_THRESHOLDS
    result = assign(jobs[0], profiles, idf, thresholds, use_llm=use_llm)
    for r in existing:
        session.delete(r)
    if not result.get("key"):
        session.flush()
        return None
    primary = JobArchetype(job_id=job_id, set_version=aset.version, archetype_id=int(result["key"]), role="primary",
                           method=result["method"], score=result.get("score"), confidence=result.get("confidence"),
                           rationale=result.get("rationale"))
    session.add(primary)
    if result.get("secondary"):
        session.add(JobArchetype(job_id=job_id, set_version=aset.version, archetype_id=int(result["secondary"]),
                                 role="secondary", method=result["method"], rationale="close second"))
    session.flush()
    return primary


def set_user_assignment(session: Session, job_id: str, archetype_id: int | None) -> None:
    aset = _active(session)
    if aset is None:
        return
    for r in session.exec(select(JobArchetype).where(JobArchetype.job_id == job_id, JobArchetype.set_version == aset.version)).all():
        session.delete(r)
    session.flush()
    if archetype_id:
        session.add(JobArchetype(job_id=job_id, set_version=aset.version, archetype_id=archetype_id, role="primary",
                                 method="user", confidence=1.0, rationale="set by you"))
    session.commit()


def confirm(session: Session, run: ClassifyRun, progress=lambda m: None) -> ArchetypeSet:
    proposal = json.loads(run.proposal)
    prev = _active(session)
    version = (max(s.version for s in session.exec(select(ArchetypeSet)).all()) + 1) if prev else 1
    aset = ArchetypeSet(version=version, status="active", notes=f"From rework run {run.id}",
                        params=json.dumps({"thresholds": proposal.get("thresholds") or DEFAULT_THRESHOLDS}))
    if prev:
        prev.status = "superseded"
        session.add(prev)
    session.add(aset)
    session.flush()
    key_to_id = {}
    for a in proposal["archetypes"]:
        row = Archetype(set_version=version, slug=a["key"], name=a["name"], definition=a["definition"],
                        include_criteria=a.get("include", ""), exclude_criteria=a.get("exclude", ""),
                        defining_skills=json.dumps(a.get("defining_skills", [])), maps_from=json.dumps(a.get("maps_from", [])))
        session.add(row)
        session.flush()
        key_to_id[a["key"]] = row.id
    for a in proposal["archetypes"]:
        for jid in a["members"]:
            session.add(JobArchetype(job_id=jid, set_version=version, archetype_id=key_to_id[a["key"]], role="primary",
                                     method="rework", rationale="confirmed in rework"))
    session.flush()

    # jobs outside the pool (market data off, or added since) get assigned against the new set
    pool_ids = set(proposal["jobs"])
    others = [j.id for j in session.exec(select(Job)).all() if j.id not in pool_ids]
    for i, jid in enumerate(others, 1):
        progress(f"Assigning jobs outside the pool {i}/{len(others)}")
        assign_job(session, jid)
    run.status = "confirmed"
    run.finished_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()
    export_notes(session, version)
    return aset


def notes_dir() -> Path:
    src = os.environ.get("PROFILE_SOURCE_DIR")
    base = Path(src).expanduser() if src else REPO_ROOT
    return base / "generated" / "archetypes"


def export_notes(session: Session, version: int) -> Path:
    """Generated archetype notes (overwritten on every confirm). Strengths and gaps
    are added in Phase 3 (market layer)."""
    out = notes_dir()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.md"):
        old.unlink()
    archetypes = session.exec(select(Archetype).where(Archetype.set_version == version)).all()
    for a in archetypes:
        member_ids = [r.job_id for r in session.exec(select(JobArchetype).where(
            JobArchetype.set_version == version, JobArchetype.archetype_id == a.id, JobArchetype.role == "primary")).all()]
        members = load_jobs(session, member_ids, market_only=True)
        skills = "\n".join(f"- {s}: {n} of {len(members)} jobs" for s, n in top_skills(members, 15)) or "- (no market-data members yet)"
        (out / f"{a.slug}.md").write_text(f"""---
generated: true
archetype_set: {version}
updated: {datetime.now(timezone.utc).date().isoformat()}
---

> Generated by job-radar on every confirmed archetype rework. Edits here are overwritten; change archetypes on the Classify page.

# {a.name}

{a.definition}

**Include:** {a.include_criteria or '-'}

**Exclude:** {a.exclude_criteria or '-'}

**Defining skills:** {', '.join(json.loads(a.defining_skills or '[]')) or '-'}

## Market-data jobs ({len(members)})

{chr(10).join(f'- {m.card.title_normalized} ({m.company})' for m in members) or '- none'}

## Most requested skills

{skills}
""")
    return out
