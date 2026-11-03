"""Application tracking: POST /jobs/{job_id}/stages, POST /jobs/{job_id}/stages/{event_id},
POST /jobs/{job_id}/stages/{event_id}/delete, POST /jobs/{job_id}/application,
GET /jobs/{job_id}/sent/cv.pdf, GET /jobs/{job_id}/sent/letter.pdf, GET /calendar.ics,
GET /jobs/{job_id}/stages/{event_id}.ics"""
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlmodel import Session, select

from app.deps import get_session
from app.services import tracking as svc
from src.cv.pdf import letter_to_pdf, markdown_to_pdf
from src.db import Job, StageEvent, Tracking
from src.letters import core as letters
from src.tracking import core

router = APIRouter()


def _job(session: Session, job_id: str) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _event(session: Session, job_id: str, event_id: int) -> StageEvent:
    ev = session.get(StageEvent, event_id)
    if ev is None or ev.job_id != job_id:
        raise HTTPException(status_code=404, detail="Entry not found")
    return ev


def _ok(session: Session, job_id: str) -> JSONResponse:
    session.commit()
    return JSONResponse({"ok": True, "application": svc.application_json(session, job_id)})


@router.post("/jobs/{job_id}/stages")
async def log_stage(job_id: str, request: Request, session: Session = Depends(get_session)):
    """Log a stage from the board or the job page (the shared Log stage form)."""
    job = _job(session, job_id)
    form = await request.form()
    try:
        core.log_stage(
            session, job_id, form.get("stage", ""), on=form.get("date"), time=form.get("time"),
            detail=svc.detail_from_form(form), note=(form.get("note") or "").strip(),
            applied_on=form.get("applied_on"), reopen=form.get("reopen") == "1", snapshot=svc.snapshot,
            kind=job.kind,
        )
        if job.kind == "event" and form.get("stage") in ("applied", "screening") and job.event_date:
            if not any(e.stage == "interview" for e in core.events_for(session, job_id)):
                core.log_stage(session, job_id, "interview", on=job.event_date, time=job.event_time, kind="event")
    except core.NeedsReopen as exc:
        session.rollback()
        return JSONResponse({"ok": False, "needs_reopen": True, "error": str(exc)}, status_code=409)
    except core.StageError as exc:
        session.rollback()
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return _ok(session, job_id)


@router.post("/jobs/{job_id}/stages/{event_id}")
async def update_stage(job_id: str, event_id: int, request: Request, session: Session = Depends(get_session)):
    ev = _event(session, job_id, event_id)
    form = await request.form()
    try:
        core.update_event(
            session, ev, on=form.get("date"), time=form.get("time"), detail=svc.detail_from_form(form),
            note=(form.get("note") or "").strip(), debrief=(form.get("debrief") or "").strip(),
            questions=(form.get("questions") or "").strip(),
        )
    except core.StageError as exc:
        session.rollback()
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return _ok(session, job_id)


@router.post("/jobs/{job_id}/stages/{event_id}/delete")
def delete_stage(job_id: str, event_id: int, session: Session = Depends(get_session)):
    core.delete_event(session, _event(session, job_id, event_id))
    return _ok(session, job_id)


@router.post("/jobs/{job_id}/application")
def save_application(
    job_id: str,
    session: Session = Depends(get_session),
    channel: str = Form(""),
    contact: str = Form(""),
    application_ref: str = Form(""),
    related_job_id: str = Form(""),
    notes: str = Form(""),
):
    """Channel, contact, portal ID, linked application and general notes (job page)."""
    _job(session, job_id)
    tr = core.ensure_tracking(session, job_id)
    tr.channel, tr.contact = channel.strip() or None, contact.strip() or None
    tr.application_ref = application_ref.strip() or None
    tr.related_job_id = related_job_id.strip() or None
    tr.notes = notes.strip() or None
    session.add(tr)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}?saved=application#application", status_code=303)


def _filename(prefix: str, job: Job) -> str:
    return f"{prefix} {job.title}, {job.company}.pdf".replace("/", "-")


@router.get("/jobs/{job_id}/sent/cv.pdf")
def sent_cv_pdf(job_id: str, session: Session = Depends(get_session)):
    """The CV in use when I applied."""
    job = _job(session, job_id)
    md = svc.sent_cv_markdown(session, job, core.ensure_tracking(session, job_id).sent_cv_ref)
    if not md:
        raise HTTPException(status_code=404, detail="No CV was recorded for this application")
    out = Path(tempfile.mkdtemp()) / _filename("CV (sent)", job)
    markdown_to_pdf(md, out)
    return FileResponse(out, media_type="application/pdf", filename=out.name)


@router.get("/jobs/{job_id}/sent/letter.pdf")
def sent_letter_pdf(job_id: str, session: Session = Depends(get_session)):
    """The cover letter version in use when I applied."""
    job = _job(session, job_id)
    letter = svc.sent_letter(session, core.ensure_tracking(session, job_id).sent_letter_id)
    if letter is None:
        raise HTTPException(status_code=404, detail="No cover letter was recorded for this application")
    out = Path(tempfile.mkdtemp()) / _filename("Cover letter (sent)", job)
    letter_to_pdf(letters.pdf_parts(session, job, letter), out)
    return FileResponse(out, media_type="application/pdf", filename=out.name)


def _ics_title(session: Session, ev: StageEvent) -> str:
    job = session.get(Job, ev.job_id)
    d = core.detail_of(ev)
    kind = f" ({d['kind']})" if d.get("kind") else ""
    return f"{core.event_label(ev, job.kind if job else 'job')}{kind}: {job.company if job else ''}, {job.title if job else ''}"


def _ics_response(body: str, name: str) -> Response:
    return Response(body, media_type="text/calendar", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/calendar.ics")
def calendar(session: Session = Depends(get_session)):
    """Every upcoming call, interview and assessment, as one calendar file."""
    open_jobs = {t.job_id for t in session.exec(select(Tracking)).all() if core.group_of(t.status) == "process"}
    events = [e for e in core.upcoming_events(session)
              if e.stage in ("screening", "interview", "assessment") and e.job_id in open_jobs]
    return _ics_response(core.ics([(e, _ics_title(session, e)) for e in events]), "job-radar.ics")


@router.get("/jobs/{job_id}/stages/{event_id}.ics")
def event_ics(job_id: str, event_id: int, session: Session = Depends(get_session)):
    ev = _event(session, job_id, event_id)
    return _ics_response(core.ics([(ev, _ics_title(session, ev))]), f"job-radar-{event_id}.ics")
