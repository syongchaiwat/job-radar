"""Board page: GET /, POST /jobs/add, POST /jobs/market-data"""
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import Session

from app.constants import ARCHIVED_STATUSES, IN_PROGRESS_STATUSES, MATCH_LEVELS, STATUS_OPTIONS
from app.deps import get_session
from app.services.jobs import active_archetypes, evidenced_skill_ids, job_archetypes, list_board_rows, ranking_for
from src.lanes.core import load_lanes
from app.templating import templates
from src.db import Job
from src.archetypes.commit import assign_job
from src.lanes.core import assess_job
from src.enrich import enrich_job
from src.ingest.dedupe import is_duplicate, job_id as url_job_id
from src.ingest.manual import build_job, create_manual_job
from src.ingest.url_fetch import fetch_and_extract
from src.screening.run import archetype_text, screen_job

router = APIRouter()


def _render_board(request: Request, session: Session, add_form: dict | None = None, added: Job | None = None):
    rows = list_board_rows(session)
    aset, archetypes = active_archetypes(session)
    arch_name = {a.id: a.name for a in archetypes}
    assignments = job_archetypes(session, aset)
    evidenced = evidenced_skill_ids(session)
    lane_names = {l.key: l.name for l in load_lanes()}
    for row in rows:
        primary = assignments.get(row["job"].id, {}).get("primary")
        row["archetype"] = arch_name.get(primary.archetype_id) if primary else None
        rank = ranking_for(session, row["job"], evidenced)
        row["priority"] = rank["priority"]
        row["eligible"] = rank["assessment"].eligible if rank["assessment"] else None
        row["lane_name"] = lane_names.get(row["job"].lane)

    jobs_json = json.dumps(
        [
            {
                "job_id": row["job"].id,
                "company": row["job"].company,
                "title": row["job"].title,
                "excluded": bool(row["screening"] and row["screening"].decision == "exclude"),
                "status": row["tracking"].status if row["tracking"] else "new",
                "first_seen": row["job"].first_seen.isoformat(),
                "match_level": row["screening"].match_level if row["screening"] else None,
                "cv_verdict": row["cv_draft"].verdict if row["cv_draft"] else None,
                "market_data": bool(row["job"].market_data),
                "priority": row["priority"],
                "lane": row["job"].lane or "none",
                "archetype": str(assignments[row["job"].id]["primary"].archetype_id) if assignments.get(row["job"].id, {}).get("primary") else "none",
            }
            for row in rows
        ]
    )
    board_config = json.dumps(
        {
            "archetypeOrder": [str(a.id) for a in archetypes],
            "statusOrder": STATUS_OPTIONS,
            "matchOrder": MATCH_LEVELS,
            "inProgress": IN_PROGRESS_STATUSES,
            "archived": ARCHIVED_STATUSES,
        }
    )

    return templates.TemplateResponse(
        request=request,
        name="board.html",
        context={
            "rows": rows,
            "jobs_json": jobs_json,
            "board_config": board_config,
            "archetype_pills": [(str(a.id), a.name) for a in archetypes],
            "lane_pills": [(l.key, l.name) for l in load_lanes()],
            "add_form": add_form or {},
            "added": added,
            "added_row": next((r for r in rows if added and r["job"].id == added.id), None),
        },
    )


@router.get("/")
def board(request: Request, added: str | None = None, session: Session = Depends(get_session)):
    added_job = session.get(Job, added) if added else None
    return _render_board(request, session, added=added_job)


@router.post("/jobs/add")
def add_job(
    request: Request,
    session: Session = Depends(get_session),
    url: str = Form(...),
    description: str = Form(""),
):
    """Same steps as scripts/add_manual_job.py + `run --job-id`, behind a form:
    dedupe -> auto-fetch (unless a description was pasted) -> insert -> screen."""
    url, description = url.strip(), description.strip()
    form = {"url": url, "description": description}
    if not url:
        return _render_board(request, session, add_form={**form, "error": "Paste a job URL first."})

    if is_duplicate(session, url):
        existing = session.get(Job, url_job_id(url))
        return _render_board(request, session, add_form={**form, "duplicate": existing})

    title = company = location = None
    if not description:
        fetched = fetch_and_extract(url)
        if fetched is None:
            # Blocked or unreachable (LinkedIn, DataDome-protected boards): ask for the text instead.
            return _render_board(request, session, add_form={**form, "needs_description": True})
        description = fetched["description"]
        title, company, location = fetched["title"], fetched["company"], fetched["location"]

    raw = build_job(url, description=description, title=title, company=company, location=location)
    job = create_manual_job(session, raw)
    session.commit()

    try:  # role card + skills + embedding + archetype first, so screening can use the archetype
        enrich_job(session, job)
        session.commit()
        assign_job(session, job.id)
        session.commit()
    except Exception:  # never blocks adding the job
        session.rollback()

    try:
        session.add(screen_job(job, archetype_text(session, job.id)))
        session.add(job)  # screen_job backfills title/company from the description
        session.commit()
    except Exception as exc:  # the job is saved either way; screening can be re-run from the CLI
        session.rollback()
        return _render_board(
            request, session, add_form={"error": f"Added the job, but screening failed: {exc}"}
        )

    try:
        assess_job(session, job)
        session.commit()
    except Exception:
        session.rollback()

    return RedirectResponse(f"/?added={job.id}", status_code=303)


@router.post("/jobs/market-data")
def set_market_data(session: Session = Depends(get_session), job_ids: list[str] = Form(...), value: str = Form(...)):
    """Market-data switch for one or many jobs (board card toggle and bulk select)."""
    flag = value == "1"
    updated = 0
    for jid in job_ids:
        job = session.get(Job, jid)
        if job is not None:
            job.market_data = flag
            session.add(job)
            updated += 1
    session.commit()
    return JSONResponse({"updated": updated, "market_data": flag})
