"""DB query helpers for the dashboard: board listing + single-job bundle.

Both apply "latest Screening per job" dedup -- Screening.job_id has no
unique constraint by design (multiple runs per job are allowed, e.g. after
a prompt fix and a targeted re-screen), so a naive join would show
duplicate/stale cards the moment a job gets re-screened.
"""
from sqlmodel import Session, select

from src.db import Archetype, ArchetypeSet, CVDraft, GroundTruth, Job, JobArchetype, JobSkill, RoleCard, Screening, Skill, Tracking


def _ensure_tracking(session: Session, job_id: str) -> Tracking:
    tr = session.exec(select(Tracking).where(Tracking.job_id == job_id)).first()
    if tr is None:
        tr = Tracking(job_id=job_id, status="new")
        session.add(tr)
        session.commit()
        session.refresh(tr)
    return tr


def _ensure_all_tracking(session: Session) -> None:
    existing_ids = {t.job_id for t in session.exec(select(Tracking)).all()}
    all_job_ids = {j.id for j in session.exec(select(Job)).all()}
    missing = all_job_ids - existing_ids
    for job_id in missing:
        session.add(Tracking(job_id=job_id, status="new"))
    if missing:
        session.commit()


def _latest_screening_by_job(session: Session) -> dict[str, Screening]:
    latest: dict[str, Screening] = {}
    for sc in session.exec(select(Screening).order_by(Screening.created_at)).all():
        latest[sc.job_id] = sc  # later rows overwrite earlier ones -> keeps the newest
    return latest


def _latest_cv_by_job(session: Session) -> dict[str, CVDraft]:
    latest: dict[str, CVDraft] = {}
    for cv in session.exec(select(CVDraft).order_by(CVDraft.created_at)).all():
        latest[cv.job_id] = cv
    return latest


def list_board_rows(session: Session) -> list[dict]:
    _ensure_all_tracking(session)
    jobs = session.exec(select(Job)).all()
    screenings = _latest_screening_by_job(session)
    trackings = {t.job_id: t for t in session.exec(select(Tracking)).all()}
    cvs = _latest_cv_by_job(session)

    return [
        {
            "job": job,
            "screening": screenings.get(job.id),
            "tracking": trackings.get(job.id),
            "cv_draft": cvs.get(job.id),
        }
        for job in jobs
    ]


def get_job_bundle(session: Session, job_id: str) -> dict | None:
    job = session.get(Job, job_id)
    if job is None:
        return None
    screening = session.exec(
        select(Screening).where(Screening.job_id == job_id).order_by(Screening.created_at.desc())
    ).first()
    tracking = _ensure_tracking(session, job_id)
    cv_versions = session.exec(
        select(CVDraft).where(CVDraft.job_id == job_id).order_by(CVDraft.created_at)
    ).all()
    return {
        "job": job,
        "screening": screening,
        "tracking": tracking,
        "cv_draft": cv_versions[-1] if cv_versions else None,
        "cv_versions": cv_versions,  # oldest first, so v1 = index 0
        "label": session.get(GroundTruth, job_id),
        "role_card": session.get(RoleCard, job_id),
        "breakdown": _cached_breakdown(job),
        **_archetype_bundle(session, job_id),
        **_cvlib_bundle(session, job),
        **_lane_bundle(session, job),
        "role_card_skills": _skills_for(session, job_id),
    }


def _skills_for(session: Session, job_id: str) -> dict[str, list[Skill]]:
    rows = session.exec(
        select(JobSkill, Skill).where(JobSkill.job_id == job_id, JobSkill.skill_id == Skill.id).order_by(Skill.name)
    ).all()
    out: dict[str, list[Skill]] = {"required": [], "nice_to_have": []}
    for link, skill in rows:
        out.setdefault(link.importance, []).append(skill)
    return out


def active_archetypes(session: Session) -> tuple[ArchetypeSet | None, list[Archetype]]:
    aset = session.exec(select(ArchetypeSet).where(ArchetypeSet.status == "active")).first()
    if aset is None:
        return None, []
    return aset, session.exec(select(Archetype).where(Archetype.set_version == aset.version).order_by(Archetype.name)).all()


def job_archetypes(session: Session, aset: ArchetypeSet | None, job_id: str | None = None) -> dict[str, dict[str, JobArchetype]]:
    """{job_id: {"primary": JobArchetype, "secondary": JobArchetype}} in the active set."""
    if aset is None:
        return {}
    q = select(JobArchetype).where(JobArchetype.set_version == aset.version)
    if job_id:
        q = q.where(JobArchetype.job_id == job_id)
    out: dict[str, dict[str, JobArchetype]] = {}
    for r in session.exec(q).all():
        out.setdefault(r.job_id, {})[r.role] = r
    return out


def _archetype_bundle(session: Session, job_id: str) -> dict:
    aset, archetypes = active_archetypes(session)
    rows = job_archetypes(session, aset, job_id).get(job_id, {})
    by_id = {a.id: a for a in archetypes}
    return {
        "archetype_set": aset,
        "archetypes": archetypes,
        "archetype_primary": rows.get("primary"),
        "archetype_secondary": rows.get("secondary"),
        "archetype_by_id": by_id,
    }


def _cached_breakdown(job: Job):
    from src.pipeline.schemas import DescriptionBreakdown

    if not job.description_breakdown:
        return None
    try:
        return DescriptionBreakdown.model_validate_json(job.description_breakdown)
    except ValueError:
        return None


def _cvlib_bundle(session: Session, job: Job) -> dict:
    from src.cvlib import library
    from src.db import CVVersion

    job_cv = library.cv_for_job(session, job)
    slot = library.lane_slot(session, job)
    latest_by_slug: dict[str, CVVersion] = {}
    for cv in session.exec(select(CVVersion).order_by(CVVersion.id)).all():
        latest_by_slug[cv.archetype_slug] = cv
    aset, archetypes = active_archetypes(session)
    by_slug = {a.slug: a for a in archetypes}
    return {
        "job_cv": job_cv,
        "job_cv_archetype": by_slug.get(job_cv.archetype_slug) if job_cv else None,
        "job_cv_markdown": library.apply_lane_slot(job_cv.draft_markdown, slot) if job_cv else "",
        "lane_sentence": slot,
        "job_archetype": library.primary_archetype(session, job.id),
        "library_cvs": [(cv, by_slug.get(slug)) for slug, cv in latest_by_slug.items()],
    }


def evidenced_skill_ids(session: Session) -> set[int]:
    from src.market.evidence import evidence

    return set(evidence(session, refresh=False))


def ranking_for(session: Session, job: Job, evidenced: set[int]) -> dict:
    from src import lanes
    from src.db import LaneAssessment

    a = session.get(LaneAssessment, job.id)
    f = lanes.fit(session, job.id, evidenced)
    u, u_note = lanes.urgency(job)
    return {"assessment": a, "fit": f, "urgency": u, "urgency_note": u_note,
            "priority": lanes.priority(f["score"], a, u)}


def _lane_bundle(session: Session, job: Job) -> dict:
    from src import letters
    from src.lanes import lane_by_key, load_lanes

    r = ranking_for(session, job, evidenced_skill_ids(session))
    return {
        "lanes": load_lanes(),
        "job_lane": lane_by_key(job.lane),
        "lane_assessment": r["assessment"],
        "fit": r["fit"], "urgency": r["urgency"], "urgency_note": r["urgency_note"], "priority": r["priority"],
        "cover_letters": letters.letters_for(session, job.id),
    }
