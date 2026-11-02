"""Application tracking for the dashboard: form parsing, the snapshot of what I sent,
and the JSON the board and job page use. Rules live in src/tracking/core.py."""
from sqlmodel import Session, select

from src.cv import library
from src.db import CoverLetter, CVVersion, Job, JobCV
from src.letters import core as letters
from src.tracking import core

DETAIL_FIELDS = ("kind", "format", "people", "platform", "due", "submitted", "rating", "round")


def detail_from_form(form) -> dict:
    out = {k: (form.get(k) or "").strip() for k in DETAIL_FIELDS}
    for k in ("rating", "round"):
        out[k] = int(out[k]) if out[k].isdigit() else ""
    return out


def snapshot(session: Session, job_id: str) -> None:
    """Freeze which CV and cover letter were in use when I applied."""
    tr = core.ensure_tracking(session, job_id)
    job = session.get(Job, job_id)
    current = library.effective_cv(session, job) if job else None
    tr.sent_cv_ref = current[1] if current else None
    cl = letters.letters_for(session, job_id)
    tr.sent_letter_id = cl[-1].id if cl else None
    session.add(tr)


def sent_cv_markdown(session: Session, job: Job, ref: str | None) -> str | None:
    """The CV I sent. A library CV is shown with the job's lane line, as it was sent."""
    if not ref or ":" not in ref:
        return None
    kind, _, rid = ref.partition(":")
    if kind == "job":
        row = session.get(JobCV, int(rid))
        return row.markdown if row else None
    cv = session.get(CVVersion, int(rid))
    return library.apply_lane_slot(cv.draft_markdown, library.lane_slot(session, job)) if cv else None


def sent_letter(session: Session, letter_id: int | None) -> CoverLetter | None:
    return session.get(CoverLetter, letter_id) if letter_id else None


def application_json(session: Session, job_id: str) -> dict:
    tr = core.ensure_tracking(session, job_id)
    return {**core.summary(core.events_for(session, job_id)), **tracking_fields(tr)}


def tracking_fields(tr) -> dict:
    return {
        "channel": tr.channel or "", "contact": tr.contact or "", "application_ref": tr.application_ref or "",
        "sent_cv": bool(tr.sent_cv_ref), "sent_cv_edited": bool(tr.sent_cv_ref and tr.sent_cv_ref.startswith("job:")),
        "sent_letter": bool(tr.sent_letter_id), "notes": tr.notes or "",
    }


def same_company_jobs(session: Session, job: Job) -> list[Job]:
    """Other jobs at the same company, for linking a repeat application."""
    key = (job.company or "").strip().lower()
    if not key:
        return []
    return [j for j in session.exec(select(Job).where(Job.id != job.id)).all() if (j.company or "").strip().lower() == key]
