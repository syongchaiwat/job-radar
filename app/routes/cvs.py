"""CV library: GET /cvs, GET /cvs/{archetype_id}, POST /cvs/{archetype_id}/generate,
GET /cvs/{archetype_id}/status, POST /cvs/version/{cv_id}/edit, GET /cvs/version/{cv_id}/pdf,
POST /jobs/{job_id}/cvlib, GET /jobs/{job_id}/cv/preview, POST /jobs/{job_id}/cv/edit,
POST /jobs/{job_id}/cv/reset, POST /jobs/{job_id}/cv/restore, GET /jobs/{job_id}/cv/pdf"""
import json
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, select

from app.deps import get_session
from app.templating import templates
from src.cv import library
from src.db import Archetype, CVVersion, Job, get_engine
from src.market.stats import market_overview
from src.cv.pdf import markdown_to_pdf

router = APIRouter()
_RUNNING: dict[int, dict] = {}  # archetype_id -> {"error": str | None}


def _generate_in_background(archetype_id: int, seed_id: int | None) -> None:
    from sqlmodel import Session as S

    try:
        with S(get_engine()) as session:
            seed = session.get(CVVersion, seed_id) if seed_id else None
            library.generate(session, archetype_id, seed)
        _RUNNING.pop(archetype_id, None)
    except Exception as exc:  # shown on the card
        _RUNNING[archetype_id] = {"error": f"{type(exc).__name__}: {exc}"}


def _cards(session: Session) -> list[dict]:
    overview = market_overview(session, refresh_evidence=False)
    out = []
    for row in overview["archetypes"]:
        a = row["archetype"]
        vs = library.versions(session, a.slug)
        latest = vs[-1] if vs else None
        out.append({"row": row, "archetype": a, "latest": latest, "n_versions": len(vs),
                    "status": library.status(session, latest, row), "running": _RUNNING.get(a.id)})
    return out


@router.get("/cvs")
def library_page(request: Request, session: Session = Depends(get_session)):
    cards = _cards(session)
    jobs_per_arch = {}
    for job in session.exec(select(Job)).all():
        a = library.primary_archetype(session, job.id)
        if a:
            jobs_per_arch[a.id] = jobs_per_arch.get(a.id, 0) + 1
    return templates.TemplateResponse(request=request, name="cv_library.html",
                                      context={"cards": cards, "jobs_per_arch": jobs_per_arch})


@router.get("/cvs/{archetype_id}")
def cv_detail(archetype_id: int, request: Request, session: Session = Depends(get_session)):
    card = next((c for c in _cards(session) if c["archetype"].id == archetype_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail="Unknown archetype")
    return templates.TemplateResponse(request=request, name="cv_detail.html",
                                      context={"card": card, "versions": library.versions(session, card["archetype"].slug)})


@router.post("/cvs/{archetype_id}/generate")
def generate(archetype_id: int, session: Session = Depends(get_session), seed_id: str = Form("")):
    if archetype_id in _RUNNING and not _RUNNING[archetype_id].get("error"):
        return RedirectResponse(f"/cvs/{archetype_id}", status_code=303)
    if session.get(Archetype, archetype_id) is None:
        raise HTTPException(status_code=404, detail="Unknown archetype")
    _RUNNING[archetype_id] = {"error": None}
    threading.Thread(target=_generate_in_background, args=(archetype_id, int(seed_id) if seed_id else None), daemon=True).start()
    return RedirectResponse(f"/cvs/{archetype_id}", status_code=303)


@router.get("/cvs/{archetype_id}/status")
def generate_status(archetype_id: int):
    state = _RUNNING.get(archetype_id)
    if state is None or state.get("error"):
        return HTMLResponse("", headers={"HX-Refresh": "true"})
    return HTMLResponse('<span class="animate-pulse">Drafting and critiquing… (2-3 minutes)</span>')


@router.post("/cvs/version/{cv_id}/edit")
def edit(cv_id: int, session: Session = Depends(get_session), markdown: str = Form(...)):
    base = session.get(CVVersion, cv_id)
    if base is None:
        raise HTTPException(status_code=404, detail="CV not found")
    markdown = markdown.replace("\r\n", "\n").strip() + "\n"
    if markdown.strip() != base.draft_markdown.strip():
        library.save_edit(session, base, markdown)
    return RedirectResponse(f"/cvs/{base.archetype_id}", status_code=303)


def _pdf_response(markdown: str, filename: str) -> FileResponse:
    out = Path(tempfile.mkdtemp()) / filename
    try:
        markdown_to_pdf(markdown, out)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=f"PDF rendering failed: {exc}")
    return FileResponse(out, media_type="application/pdf", filename=filename)


@router.get("/cvs/version/{cv_id}/pdf")
def version_pdf(cv_id: int, session: Session = Depends(get_session)):
    cv = session.get(CVVersion, cv_id)
    if cv is None:
        raise HTTPException(status_code=404, detail="CV not found")
    return _pdf_response(cv.draft_markdown, f"CV_{cv.archetype_slug}_v{cv.id}.pdf")


@router.post("/jobs/{job_id}/cvlib")
def choose_cv(job_id: str, session: Session = Depends(get_session), cv_version_id: str = Form("")):
    """Which library CV this job uses ('' = follow the latest CV of its archetype). If the job has an
    edited copy, this starts over from the chosen CV (the edited versions stay as history)."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job.cv_version_id = int(cv_version_id) if cv_version_id else None
    session.add(job)
    library.reset_job_cv(session, job_id)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}#cv-library", status_code=303)


@router.get("/jobs/{job_id}/cv/preview")
def preview_job_cv(job_id: str, pick: str = "", cv_version_id: str = "", job_cv_id: str = "", session: Session = Depends(get_session)):
    """Markdown of a candidate CV for this job, without changing anything: the last saved copy
    (pick=saved, job_cv_id = one of its versions, default the newest) or a library version with the job's lane line ('' = latest of the job's archetype)."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if pick == "saved":
        rows = library.job_cv_versions(session, job_id)
        row = next((r for r in rows if str(r.id) == job_cv_id), None) if job_cv_id else (rows[0] if rows else None)
        return JSONResponse({"markdown": row.markdown if row else ""})
    if cv_version_id:
        cv = session.get(CVVersion, int(cv_version_id))
    else:
        a = library.primary_archetype(session, job_id)
        vs = library.versions(session, a.slug) if a else []
        cv = vs[-1] if vs else None
    md = library.apply_lane_slot(cv.draft_markdown, library.lane_slot(session, job)) if cv else ""
    return JSONResponse({"markdown": md})


@router.post("/jobs/{job_id}/cv/restore")
def restore_job_cv(job_id: str, session: Session = Depends(get_session), job_cv_id: str = Form("")):
    """Use one of this job's saved CVs again (default: the newest)."""
    library.restore_job_cv(session, job_id, int(job_cv_id) if job_cv_id else None)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}#cv-library", status_code=303)


@router.post("/jobs/{job_id}/cv/edit")
def edit_job_cv(job_id: str, session: Session = Depends(get_session), markdown: str = Form(...), base_cv_version_id: str = Form("")):
    """Save an edit of this job's CV (a new version for this job only; the library CV is untouched)."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    current = library.effective_cv(session, job)
    if current is None or markdown.replace("\r\n", "\n").strip() != current[0].strip():
        edited = library.job_cv(session, job_id)
        base = int(base_cv_version_id) if base_cv_version_id else (edited.base_cv_version_id if edited else None)
        library.save_job_cv(session, job, markdown, base)
        session.commit()
    return RedirectResponse(f"/jobs/{job_id}#cv-library", status_code=303)


@router.post("/jobs/{job_id}/cv/reset")
def reset_job_cv(job_id: str, session: Session = Depends(get_session)):
    """Back to the library CV; the edited versions stay in the database as history."""
    library.reset_job_cv(session, job_id)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}#cv-library", status_code=303)


@router.get("/jobs/{job_id}/cv/pdf")
def job_cv_pdf(job_id: str, session: Session = Depends(get_session)):
    """PDF of what this job sends: its edited CV, else the library CV with the lane line."""
    job = session.get(Job, job_id)
    current = library.effective_cv(session, job) if job else None
    if current is None:
        raise HTTPException(status_code=404, detail="No CV for this job yet")
    return _pdf_response(current[0], f"CV_{job.company or 'job'}.pdf".replace(" ", "_").replace("/", "-"))
