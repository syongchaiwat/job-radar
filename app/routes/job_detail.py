"""Job Detail page: GET /jobs/{job_id}, POST /jobs/{job_id}/review,
POST /jobs/{job_id}/description, GET /jobs/{job_id}/breakdown, POST /jobs/{job_id}/market-data,
POST /jobs/{job_id}/archetype, POST /jobs/{job_id}/lane, POST /jobs/{job_id}/deadline, cover letters"""
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session

from app.constants import STATUS_OPTIONS
from app.deps import get_session
from app.services.jobs import enrich_and_match, get_job_bundle
from src.db import Job
from src.tracking import core as tracking_core
from app.templating import templates
from src.enrich.breakdown import compute_breakdown
from src.screening.run import archetype_text, screen_job
from src.llm.schemas import DescriptionBreakdown

router = APIRouter()


@router.get("/jobs/{job_id}")
def job_detail(job_id: str, request: Request, session: Session = Depends(get_session)):
    bundle = get_job_bundle(session, job_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return templates.TemplateResponse(
        request=request,
        name="job_detail.html",
        context={
            **bundle,
            "status_options": STATUS_OPTIONS,
        },
    )


@router.post("/jobs/{job_id}/review")
def review(job_id: str, session: Session = Depends(get_session), action: str = Form(...)):
    """Review bar (before applying): shortlist, skip, or back to the review queue."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        if action == "reset":
            tracking_core.reset_triage(session, job_id)
        elif action in ("shortlist", "skipped"):
            tracking_core.log_stage(session, job_id, action, kind=job.kind)
        else:
            raise HTTPException(status_code=400, detail="Unknown review action")
    except tracking_core.StageError as exc:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(exc))
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/lab")
def save_lab(job_id: str, session: Session = Depends(get_session), company: str = Form(...), title: str = Form(...),
             contact: str = Form(""), location: str = Form("")):
    """Lab outreach entry: lab name, topic, professor and city (job page Lab panel)."""
    job = session.get(Job, job_id)
    if job is None or job.kind != "outreach":
        raise HTTPException(status_code=404, detail="Lab entry not found")
    job.company, job.title = company.strip() or job.company, title.strip() or job.title
    job.location = location.strip() or None
    tr = tracking_core.ensure_tracking(session, job_id)
    tr.contact = contact.strip() or None
    session.add_all([job, tr])
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/event")
def save_event(job_id: str, session: Session = Depends(get_session), company: str = Form(...), title: str = Form(...),
               event_date: str = Form(""), event_time: str = Form(""), location: str = Form(""), deadline: str = Form("")):
    """Event entry: name, host, date and time, place, registration deadline (job page Event panel).
    A scheduled Event entry that hasn't happened yet moves with the new date."""
    job = session.get(Job, job_id)
    if job is None or job.kind != "event":
        raise HTTPException(status_code=404, detail="Event not found")
    job.company, job.title = company.strip() or job.company, title.strip() or job.title
    job.event_date, job.event_time = event_date or None, event_time or None
    job.location, job.deadline = location.strip() or None, deadline or None
    session.add(job)
    upcoming = [e for e in tracking_core.events_for(session, job_id) if e.stage == "interview" and e.date > tracking_core.today()]
    if upcoming and job.event_date:
        ev = upcoming[-1]
        tracking_core.update_event(session, ev, on=job.event_date, time=job.event_time, detail=tracking_core.detail_of(ev),
                                   note=ev.note, debrief=ev.debrief, questions=ev.questions)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/description")
def replace_description(job_id: str, session: Session = Depends(get_session), description: str = Form(...)):
    """Swap in a pasted description (e.g. auto-fetch saved page chrome instead of
    the posting) and re-screen. normalize_node re-extracts title/company only if
    they're still missing, so good titles on other jobs are never overwritten."""
    bundle = get_job_bundle(session, job_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Job not found")
    description = description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="Paste a description first.")
    job = bundle["job"]
    job.description = description
    job.description_breakdown = None  # cached breakdown was computed from the old text
    job.description_breakdown_computed_at = None
    session.commit()
    if job.kind != "job":  # labs and events are never screened
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)
    error = enrich_and_match(session, job, force=True)  # the role card must follow the new text
    session.add(screen_job(job, archetype_text(session, job.id)))
    session.add(job)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}" + (f"?enrich_error={quote(error)}" if error else ""), status_code=303)


@router.post("/jobs/{job_id}/enrich")
def retry_enrich(job_id: str, session: Session = Depends(get_session)):
    """Retry the role card, archetype and lane (e.g. after a failed LLM call when the job was added)."""
    bundle = get_job_bundle(session, job_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Job not found")
    error = enrich_and_match(session, bundle["job"])
    return RedirectResponse(f"/jobs/{job_id}" + (f"?enrich_error={quote(error)}" if error else ""), status_code=303)


@router.get("/jobs/{job_id}/breakdown")
def job_breakdown(job_id: str, request: Request, session: Session = Depends(get_session)):
    bundle = get_job_bundle(session, job_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job = bundle["job"]
    if job.description_breakdown is None:
        breakdown = compute_breakdown(job)
        job.description_breakdown = breakdown.model_dump_json()
        job.description_breakdown_computed_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()
    else:
        breakdown = DescriptionBreakdown.model_validate_json(job.description_breakdown)
    return templates.TemplateResponse(
        request=request,
        name="partials/_breakdown.html",
        context={"job": job, "breakdown": breakdown, "is_truncated": job.source == "adzuna"},
    )


@router.post("/jobs/{job_id}/market-data")
def toggle_market_data(job_id: str, session: Session = Depends(get_session), value: str = Form(...)):
    bundle = get_job_bundle(session, job_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job = bundle["job"]
    job.market_data = value == "1"
    session.add(job)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/archetype")
def set_archetype(job_id: str, session: Session = Depends(get_session), archetype: str = Form(...)):
    """'auto' re-runs automatic matching; 'none' clears; an id pins it (method=user)."""
    from src.archetypes.commit import assign_job, set_user_assignment

    if get_job_bundle(session, job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if archetype == "auto":
        set_user_assignment(session, job_id, None)
        assign_job(session, job_id)
        session.commit()
    else:
        set_user_assignment(session, job_id, None if archetype == "none" else int(archetype))
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/lane")
def set_lane(job_id: str, session: Session = Depends(get_session), lane: str = Form(...)):
    from src.db import Job
    from src.lanes.core import assess_job

    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if lane == "auto":
        job.lane, job.lane_source = None, None
    else:
        job.lane, job.lane_source = lane, "user"
    session.add(job)
    assess_job(session, job)  # eligibility and value depend on the lane
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/deadline")
def set_deadline(job_id: str, session: Session = Depends(get_session), deadline: str = Form("")):
    from src.db import Job

    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job.deadline = deadline or None
    session.add(job)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/letter")
def write_letter(job_id: str, session: Session = Depends(get_session), seed_id: str = Form("")):
    from src.letters import core as letters
    from src.db import CoverLetter, Job

    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    seed = session.get(CoverLetter, int(seed_id)) if seed_id else None
    try:
        letters.generate(session, job, seed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(f"/jobs/{job_id}#cover-letter", status_code=303)


def _letter_and_job(session: Session, letter_id: int):
    from src.db import CoverLetter, Job

    letter = session.get(CoverLetter, letter_id)
    if letter is None:
        raise HTTPException(status_code=404, detail="Letter not found")
    return letter, session.get(Job, letter.job_id)


@router.post("/jobs/letter/{letter_id}/edit")
def edit_letter(letter_id: int, session: Session = Depends(get_session), body: str = Form(...),
                header: str = Form(""), subject: str = Form("")):
    """Save body, header lines and subject as a new version. Header/subject equal to the
    automatic ones are not stored, so they keep following the defaults (e.g. today's date)."""
    from src.letters import core as letters

    base, job = _letter_and_job(session, letter_id)
    norm = lambda t: t.replace("\r\n", "\n").strip()  # noqa: E731
    body, header, subject = norm(body), norm(header), norm(subject)
    auto_header, auto_subject = letters.default_header(job), letters._subject(session, job)
    new_header = header if header and header != auto_header else None
    new_subject = subject if subject and subject != auto_subject else None
    if (body, new_header, new_subject) != (base.body_markdown.strip(), base.header, base.subject):
        letters.save_edit(session, base, body, new_header, new_subject)
    return RedirectResponse(f"/jobs/{base.job_id}#cover-letter", status_code=303)


@router.get("/jobs/letter/{letter_id}/pdf")
def letter_pdf(letter_id: int, session: Session = Depends(get_session)):
    import tempfile
    from pathlib import Path as P

    from src.letters import core as letters
    from src.db import CoverLetter, Job

    letter = session.get(CoverLetter, letter_id)
    if letter is None:
        raise HTTPException(status_code=404, detail="Letter not found")
    job = session.get(Job, letter.job_id)
    name = f"Cover letter {job.title}, {job.company}".replace("/", "-")
    out = P(tempfile.mkdtemp()) / f"{name}.pdf"
    from src.cv.pdf import letter_to_pdf

    letter_to_pdf(letters.pdf_parts(session, job, letter), out)
    return FileResponse(out, media_type="application/pdf", filename=out.name)
