"""Classify page (archetype rework): GET /classify, POST /classify/run, GET /classify/progress,
POST /classify/{run_id}/{rename|merge|rewrite|split|move|discard|confirm}"""
import json
import os
import threading
from pathlib import Path


from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from app.deps import get_session
from app.templating import templates
from src.archetypes import commit, rework
from src.db import DEFAULT_DB_PATH, ClassifyRun, Job, JobArchetype, Skill, get_engine

router = APIRouter()

PALETTE = ["#a78bfa", "#60a5fa", "#4ade80", "#fbbf24", "#f472b6", "#2dd4bf", "#fb923c", "#c084fc", "#94a3b8", "#f87171"]


def _latest_run(session: Session) -> ClassifyRun | None:
    """The most recent run, shown only while it still needs attention: an older
    failure must not resurface once a later run was confirmed or discarded."""
    run = session.exec(select(ClassifyRun).order_by(ClassifyRun.id.desc())).first()
    return run if run and run.status in ("running", "draft", "failed") else None


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
    draft_points, draft_legend = [], []
    current_points, current_legend = ([], []) if proposal or not aset else _current_map(session, aset, current, counts)
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
            draft_points.append({"job_id": jid, "px": info["px"], "py": info["py"], "color": info["color"], "hollow": False,
                                 "ring": info.get("flagged"), "title": info["title"], "company": info["company"],
                                 "lane": info["lane"], "arch": info["arch_name"],
                                 "note": ("flagged: " + info["flag_note"]) if info.get("flagged") else ""})
        draft_legend = [(a["name"], colors[a["key"]]) for a in sorted(proposal["archetypes"], key=lambda a: -a["stats"]["size"])]
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
            "draft_points": draft_points, "draft_legend": draft_legend,
            "current_points": current_points, "current_legend": current_legend,
        },
    )


LAYOUT_PATH = Path(os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)).parent / "classify_layout.json"


def _load_layout() -> dict:
    try:
        return json.loads(LAYOUT_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _layout(session: Session, aset, force: bool = False) -> dict[str, tuple[float, float]]:
    """2D positions for the map, saved to disk so restarts don't rerun UMAP.
    UMAP reruns only when the set of jobs changed (or a new archetype set / on request)."""
    from src.archetypes.features import combined_matrix, load_jobs, skill_idf

    pool = load_jobs(session)
    if len(pool) < 6:
        return {}
    ids = [pj.job_id for pj in pool]
    saved = _load_layout()
    if not force and saved.get("version") == aset.version and sorted(saved.get("coords", {})) == ids:
        return {k: tuple(v) for k, v in saved["coords"].items()}
    from src.archetypes.track1 import layout_2d

    xy = layout_2d(combined_matrix(pool, skill_idf(pool)))
    coords = {jid: (float(xy[i, 0]), float(xy[i, 1])) for i, jid in enumerate(ids)}
    LAYOUT_PATH.write_text(json.dumps({"version": aset.version, "coords": coords}))
    return coords


def _current_map(session: Session, aset, archetypes, counts) -> tuple[list, list]:
    """Map of every job with a role card, colored by its archetype in the active set."""
    from src.archetypes.features import load_jobs

    pool = load_jobs(session)
    coords = _layout(session, aset)
    if not coords:
        return [], []
    order = sorted(archetypes, key=lambda a: -counts.get(a.id, 0))
    color = {a.id: PALETTE[i % len(PALETTE)] for i, a in enumerate(order)}
    name = {a.id: a.name for a in archetypes}
    rows = {r.job_id: r for r in session.exec(select(JobArchetype).where(JobArchetype.set_version == aset.version, JobArchetype.role == "primary")).all()}
    market = {j.id for j in session.exec(select(Job).where(Job.market_data == True)).all()}  # noqa: E712
    xs = [c[0] for c in coords.values()]
    ys = [c[1] for c in coords.values()]
    method_note = {"llm": "matched by the LLM", "embedding": "matched directly", "user": "set by you", "rework": "", "legacy": ""}
    points = []
    for pj in pool:
        x, y = coords[pj.job_id]
        r = rows.get(pj.job_id)
        points.append({
            "job_id": pj.job_id,
            "px": 20 + 560 * (x - min(xs)) / ((max(xs) - min(xs)) or 1),
            "py": 20 + 300 * (y - min(ys)) / ((max(ys) - min(ys)) or 1),
            "color": color.get(r.archetype_id, "#4b5563") if r else "#4b5563",
            "hollow": pj.job_id not in market,
            "ring": bool(r and r.method == "llm"),
            "title": pj.title, "company": pj.company, "lane": pj.lane,
            "arch": name.get(r.archetype_id, "no archetype") if r else "no archetype",
            "note": method_note.get(r.method, "") if r else "",
        })
    legend = [(a.name, color[a.id]) for a in order] + [("no archetype", "#4b5563")]
    return points, legend


@router.post("/classify/relayout")
def relayout(session: Session = Depends(get_session)):
    aset = rework.active_set(session)
    if aset:
        _layout(session, aset, force=True)
    return RedirectResponse("/classify#map", status_code=303)


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
