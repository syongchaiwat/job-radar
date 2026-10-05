"""CV library: GET /cvs, GET /cvs/{archetype_id}, POST /cvs/{archetype_id}/generate,
GET /cvs/{archetype_id}/status, POST /cvs/version/{cv_id}/edit, GET /cvs/version/{cv_id}/pdf,
POST /jobs/{job_id}/cvlib, GET /jobs/{job_id}/cvlib/pdf"""
import json
import tempfile
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.deps import get_session
from app.templating import templates
from src.cvlib import library
from src.db import Archetype, CVVersion, Job, get_engine
from src.market.stats import market_overview
from src.pipeline.cv_pdf import markdown_to_pdf

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
    """Which library CV this job uses ('' = follow the latest CV of its archetype)."""
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    job.cv_version_id = int(cv_version_id) if cv_version_id else None
    session.add(job)
    session.commit()
    return RedirectResponse(f"/jobs/{job_id}#cv-library", status_code=303)


@router.get("/jobs/{job_id}/cvlib/pdf")
def job_cv_pdf(job_id: str, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    cv = library.cv_for_job(session, job) if job else None
    if cv is None:
        raise HTTPException(status_code=404, detail="No library CV for this job")
    markdown = library.apply_lane_slot(cv.draft_markdown, library.lane_slot(session, job))
    return _pdf_response(markdown, f"CV_{job.company or 'job'}_{cv.archetype_slug}.pdf".replace(" ", "_"))
