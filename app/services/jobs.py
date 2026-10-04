"""DB query helpers for the dashboard: board listing + single-job bundle.

Both apply "latest Screening per job" dedup -- Screening.job_id has no
unique constraint by design (multiple runs per job are allowed, e.g. after
a prompt fix and a targeted re-screen), so a naive join would show
duplicate/stale cards the moment a job gets re-screened.
"""
from sqlmodel import Session, select

from src.db import CVDraft, GroundTruth, Job, JobSkill, RoleCard, Screening, Skill, Tracking


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
