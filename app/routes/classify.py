"""Classify page (archetype rework): GET /classify, POST /classify/run, GET /classify/progress,
POST /classify/{run_id}/{rename|merge|rewrite|split|move|discard|confirm}"""
import json
import threading

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.deps import get_session
from app.templating import templates
from src.archetypes import commit, rework
from src.db import ClassifyRun, Job, JobArchetype, Skill, get_engine

router = APIRouter()

PALETTE = ["#a78bfa", "#60a5fa", "#4ade80", "#fbbf24", "#f472b6", "#2dd4bf", "#fb923c", "#c084fc", "#94a3b8", "#f87171"]


def _latest_run(session: Session) -> ClassifyRun | None:
    return session.exec(select(ClassifyRun).where(ClassifyRun.status.in_(["running", "draft", "failed"])).order_by(ClassifyRun.id.desc())).first()


def _run_or_404(session: Session, run_id: int, status: str = "draft") -> ClassifyRun:
    run = session.get(ClassifyRun, run_id)
    if run is None or run.status != status:
        raise HTTPException(status_code=404, detail=f"No {status} rework run {run_id}")
    return run


@router.get("/classify")
def classify_page(request: Request, session: Session = Depends(get_session)):
    aset = rework.active_set(session)
    current = rework.current_archetypes(session)
    counts = {}
    if aset:
        for r in session.exec(select(JobArchetype).where(JobArchetype.set_version == aset.version, JobArchetype.role == "primary")).all():
            counts[r.archetype_id] = counts.get(r.archetype_id, 0) + 1
    jobs = session.exec(select(Job)).all()
    assigned = {r.job_id for r in session.exec(select(JobArchetype).where(JobArchetype.set_version == aset.version)).all()} if aset else set()
    run = _latest_run(session)
    proposal = rework.load_proposal(run) if run and run.status == "draft" else None
    colors = {}
    retired = []
    if proposal:
        for i, a in enumerate(sorted(proposal["archetypes"], key=lambda a: -a["stats"]["size"])):
            colors[a["key"]] = PALETTE[i % len(PALETTE)]
        continued = {cid for a in proposal["archetypes"] for cid in a["maps_from"]}
        retired = [c for c in current if c.id not in continued]
        xs = [j["x"] for j in proposal["jobs"].values()] or [0]
        ys = [j["y"] for j in proposal["jobs"].values()] or [0]
        span = (min(xs), max(xs), min(ys), max(ys))
        member_of = {j: a["key"] for a in proposal["archetypes"] for j in a["members"]}
        for jid, info in proposal["jobs"].items():
            info["px"] = 20 + 560 * (info["x"] - span[0]) / ((span[1] - span[0]) or 1)
            info["py"] = 20 + 300 * (info["y"] - span[2]) / ((span[3] - span[2]) or 1)
            info["color"] = colors.get(member_of.get(jid), "#4b5563")
            names = {a["key"]: a["name"] for a in proposal["archetypes"]}
            info["arch_name"] = names.get(member_of.get(jid), "no archetype")
            info["flag_note"] = f"closer to {names.get(info.get('check'), info.get('check'))}" if info.get("flagged") else ""
    return templates.TemplateResponse(
        request=request,
        name="classify.html",
        context={
            "aset": aset, "current": current, "counts": counts, "n_jobs": len(jobs),
            "n_market": sum(1 for j in jobs if j.market_data), "n_unassigned": sum(1 for j in jobs if j.id not in assigned),
            "n_outdated": len(rework.outdated_cards(session)),
            "n_pending_skills": len(session.exec(select(Skill).where(Skill.status == "pending")).all()),
            "run": run, "proposal": proposal, "colors": colors, "retired": retired,
            "current_by_id": {c.id: c for c in current},
        },
    )


@router.post("/classify/run")
def start(session: Session = Depends(get_session)):
    if session.exec(select(ClassifyRun).where(ClassifyRun.status == "running")).first():
        return RedirectResponse("/classify", status_code=303)
    for old in session.exec(select(ClassifyRun).where(ClassifyRun.status.in_(["draft", "failed"]))).all():
        old.status = "discarded"
        session.add(old)
    session.commit()
    run = rework.start_run(session)
    threading.Thread(target=rework.execute, args=(run.id, get_engine()), daemon=True).start()
    return RedirectResponse("/classify", status_code=303)


@router.get("/classify/progress")
def progress(session: Session = Depends(get_session)):
    run = session.exec(select(ClassifyRun).order_by(ClassifyRun.id.desc())).first()
    if run is None or run.status != "running":
        return HTMLResponse("", headers={"HX-Refresh": "true"})
    return HTMLResponse(f'<span class="animate-pulse">{run.progress}</span>')


@router.post("/classify/{run_id}/rename")
def rename(run_id: int, session: Session = Depends(get_session), key: str = Form(...), name: str = Form(...), definition: str = Form("")):
    run = _run_or_404(session, run_id)
    p = rework.load_proposal(run)
    rework.edit_rename(p, key, name, definition)
    rework.save_proposal(session, run, p)
    return RedirectResponse(f"/classify#a-{key}", status_code=303)


@router.post("/classify/{run_id}/merge")
def merge(run_id: int, session: Session = Depends(get_session), keys: list[str] = Form(...), name: str = Form("")):
    run = _run_or_404(session, run_id)
    p = rework.load_proposal(run)
    rework.edit_merge(session, p, keys, name)
    rework.save_proposal(session, run, p)
    return RedirectResponse("/classify", status_code=303)


@router.post("/classify/{run_id}/rewrite")
def rewrite(run_id: int, session: Session = Depends(get_session), key: str = Form(...)):
    run = _run_or_404(session, run_id)
    p = rework.load_proposal(run)
    rework.edit_rewrite(session, p, key)
    rework.save_proposal(session, run, p)
    return RedirectResponse(f"/classify#a-{key}", status_code=303)


@router.post("/classify/{run_id}/split")
def split(run_id: int, session: Session = Depends(get_session), key: str = Form(...)):
    run = _run_or_404(session, run_id)
    p = rework.load_proposal(run)
    rework.edit_split(session, p, key)
    rework.save_proposal(session, run, p)
    return RedirectResponse("/classify", status_code=303)


@router.post("/classify/{run_id}/move")
def move(run_id: int, session: Session = Depends(get_session), job_id: str = Form(...), target: str = Form(...)):
    run = _run_or_404(session, run_id)
    p = rework.load_proposal(run)
    rework.edit_move(p, job_id, target)
    rework.save_proposal(session, run, p)
    return RedirectResponse(f"/classify#a-{target}", status_code=303)


@router.post("/classify/{run_id}/discard")
def discard(run_id: int, session: Session = Depends(get_session)):
    run = session.get(ClassifyRun, run_id)
    if run and run.status in ("draft", "failed"):
        run.status = "discarded"
        session.add(run)
        session.commit()
    return RedirectResponse("/classify", status_code=303)


@router.post("/classify/{run_id}/confirm")
def confirm(run_id: int, session: Session = Depends(get_session)):
    run = _run_or_404(session, run_id)
    commit.confirm(session, run)
    return RedirectResponse("/classify?confirmed=1", status_code=303)
