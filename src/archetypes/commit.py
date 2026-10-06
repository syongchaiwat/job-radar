"""Archetype sets: confirm a rework proposal into a new version, assign
individual jobs, export generated notes to the vault."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from sqlmodel import Session, select

from src.archetypes.assign import DEFAULT_THRESHOLDS, Profile, assign, build_profiles
from src.archetypes.features import load_jobs, skill_idf, top_skills
from src.db import Archetype, ArchetypeSet, ClassifyRun, Job, JobArchetype

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _active(session: Session) -> ArchetypeSet | None:
    return session.exec(select(ArchetypeSet).where(ArchetypeSet.status == "active")).first()


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


def _list(items: list[dict], with_sources: bool = False) -> str:
    if not items:
        return "- none"
    return "\n".join(
        f"- {d['skill']}: {round(d['share'] * 100)}% of jobs" + (f" (from {', '.join(d['sources'][:3])})" if with_sources and d.get("sources") else "")
        for d in items
    )


def export_notes(session: Session, version: int) -> Path:
    """Generated archetype notes (overwritten on every confirm, refreshable from the Market page)."""
    out = notes_dir()
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.md"):
        old.unlink()
    archetypes = session.exec(select(Archetype).where(Archetype.set_version == version)).all()
    from src.market.stats import market_overview

    market = {r["archetype"].id: r for r in market_overview(session)["archetypes"]}
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

## Strengths (asked by ≥15% of jobs, proven by your profile)

{_list(market.get(a.id, {}).get("strengths", []), with_sources=True)}

## Gaps (asked by ≥15% of jobs, no evidence yet)

{_list(market.get(a.id, {}).get("gaps", []))}

Profile coverage of this archetype's demand: {round((market.get(a.id, {}).get("coverage") or 0) * 100)}%
""")
    return out
