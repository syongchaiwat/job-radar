"""Job Detail page: GET /jobs/{job_id}, POST /jobs/{job_id}/tracking, POST /jobs/{job_id}/review,
POST /jobs/{job_id}/description, GET /jobs/{job_id}/breakdown, POST /jobs/{job_id}/market-data,
POST /jobs/{job_id}/archetype, POST /jobs/{job_id}/lane, POST /jobs/{job_id}/deadline, cover letters"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlmodel import Session

from app.constants import STATUS_OPTIONS
from app.deps import get_session
from app.services.jobs import get_job_bundle
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


REVIEW_ACTIONS = {"archive": "ignored", "shortlist": "shortlist", "reset": "new"}


@router.post("/jobs/{job_id}/review")
def review(job_id: str, session: Session = Depends(get_session), action: str = Form(...)):
    """Review bar: only sets tracking status. Preparing a CV stays a separate button (D4)."""
    bundle = get_job_bundle(session, job_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if action not in REVIEW_ACTIONS:
        raise HTTPException(status_code=400, detail="Unknown review action")
    tr = bundle["tracking"]
    tr.status = REVIEW_ACTIONS[action]
    tr.updated_at = datetime.now(timezone.utc)
    session.add(tr)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/tracking")
def save_tracking(
    job_id: str,
    request: Request,
    session: Session = Depends(get_session),
    status: str = Form(...),
    notes: str = Form(""),
):
    bundle = get_job_bundle(session, job_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="Job not found")
    tr = bundle["tracking"]
    tr.status = status
    tr.notes = notes
    tr.updated_at = datetime.now(timezone.utc)
    session.add(tr)
    session.commit()
    session.refresh(tr)
    bundle["tracking"] = tr
    return templates.TemplateResponse(
        request=request,
        name="partials/_tracking_panel.html",
        context={**bundle, "status_options": STATUS_OPTIONS, "saved": True},
    )


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
    session.add(screen_job(job, archetype_text(session, job.id)))
    session.add(job)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


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


@router.post("/jobs/letter/{letter_id}/edit")
def edit_letter(letter_id: int, session: Session = Depends(get_session), body: str = Form(...)):
    from src.letters import core as letters
    from src.db import CoverLetter

    base = session.get(CoverLetter, letter_id)
    if base is None:
        raise HTTPException(status_code=404, detail="Letter not found")
    body = body.replace("\r\n", "\n").strip()
    if body != base.body_markdown.strip():
        letters.save_edit(session, base, body)
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
    out = P(tempfile.mkdtemp()) / f"Cover_letter_{(job.company or 'job').replace(' ', '_')}.pdf"
    from src.cv.pdf import letter_to_pdf

    letter_to_pdf(*letters.pdf_parts(job, letter), out)
    return FileResponse(out, media_type="application/pdf", filename=out.name)
