"""Board page: GET /, POST /jobs/add, POST /jobs/market-data, POST /jobs/{job_id}/bookmark"""
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlmodel import Session

from app.constants import MATCH_LEVELS, OUTCOME_STATUSES, PROCESS_STATUSES, STATUS_LABELS, STATUS_OPTIONS, TRIAGE_STATUSES
from app.services.tracking import tracking_fields
from app.deps import get_session
from app.services.jobs import active_archetypes, enrich_and_match, evidenced_skill_ids, job_archetypes, list_board_rows, ranking_for
from src.lanes.core import job_lanes, load_lanes
from app.templating import templates
from src.cv import library
from src.db import Job
from src.tracking.core import EVENT_LABELS, OUTREACH_LABELS
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
    cv_names = library.cv_names(session)
    for row in rows:
        job = row["job"]
        row["lane_name"] = lane_names.get(job.lane)
        if job.kind != "job":  # no archetype, screening or ranking for labs and events
            row["archetype"], row["priority"], row["eligible"] = None, 0, None
            cv = library.cv_for_job(session, job)
            row["cv_name"] = (f"Edited for this {'lab' if job.kind == 'outreach' else 'event'}" if row["own_cv"]
                              else (cv_names.get(cv.archetype_slug) if cv else None))
            continue
        primary = assignments.get(job.id, {}).get("primary")
        row["archetype"] = arch_name.get(primary.archetype_id) if primary else None
        rank = ranking_for(session, job, evidenced)
        row["priority"] = rank["priority"]
        row["eligible"] = rank["assessment"].eligible if rank["assessment"] else None

    jobs_json = json.dumps(
        [
            {
                "job_id": row["job"].id,
                "kind": row["job"].kind,
                "event_date": row["job"].event_date,
                "event_time": row["job"].event_time,
                "cv_name": row.get("cv_name"),
                "company": row["job"].company,
                "title": row["job"].title,
                "excluded": bool(row["screening"] and row["screening"].decision == "exclude"),
                "status": row["tracking"].status if row["tracking"] else "new",
                "first_seen": row["job"].first_seen.isoformat(),
                "match_level": row["screening"].match_level if row["screening"] else None,
                "own_cv": row["own_cv"],
                "market_data": bool(row["job"].market_data),
                "bookmarked": bool(row["job"].bookmarked),
                "priority": row["priority"],
                "lane": row["job"].lane or "none",
                "archetype": str(assignments[row["job"].id]["primary"].archetype_id) if assignments.get(row["job"].id, {}).get("primary") else "none",
                # tracking table
                "archetype_name": row["archetype"],
                "lane_name": row["lane_name"],
                "eligible": row["eligible"],
                "location": row["job"].location,
                "deadline": row["job"].deadline,
                "source": row["job"].source,
                "app": row["app"],
                **(tracking_fields(row["tracking"]) if row["tracking"] else {}),
            }
            for row in rows
        ]
    )
    board_config = json.dumps(
        {
            "archetypeOrder": [str(a.id) for a in archetypes],
            "statusOrder": STATUS_OPTIONS,
            "matchOrder": MATCH_LEVELS,
            "triage": TRIAGE_STATUSES,
            "process": PROCESS_STATUSES,
            "outcome": OUTCOME_STATUSES,
            "statusLabels": STATUS_LABELS,
            "outreachLabels": OUTREACH_LABELS,
            "eventLabels": EVENT_LABELS,
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
            "lane_pills": [(l.key, l.name) for l in job_lanes()],
            "add_form": add_form or {},
            "n_labs": sum(1 for r in rows if r["job"].kind == "outreach"),
            "n_events": sum(1 for r in rows if r["job"].kind == "event"),
            "added": added,
            "added_row": next((r for r in rows if added and r["job"].id == added.id), None),
        },
    )


@router.get("/")
def board(request: Request, added: str | None = None, session: Session = Depends(get_session)):
    added_job = session.get(Job, added) if added else None
    return _render_board(request, session, added=added_job)


def _add_lab(request: Request, session: Session, url: str, description: str, form: dict):
    """Lab outreach entry: fetch (or take the pasted text), extract the lab, insert. No screening,
    archetype or lane assessment: it starts as To contact, in the academic-thesis lane."""
    from src.ingest.url_fetch import extract_lab, fetch_lab_page
    from src.lanes.core import OUTREACH_LANE
    from src.tracking import core as tracking_core

    lab = extract_lab(description, pasted=True) if description else fetch_lab_page(url)
    if lab is None:
        return _render_board(request, session, add_form={**form, "needs_description": True})
    area = (lab.get("research_area") or "").strip()
    raw = build_job(url, description=lab["description"], title=f"Thesis: {area}" if area else "Thesis topics",
                    company=lab.get("lab") or "Unknown lab", location=lab.get("location") or None)
    job = create_manual_job(session, raw)
    job.kind, job.lane, job.lane_source = "outreach", OUTREACH_LANE, "user"
    session.add(job)
    tr = tracking_core.ensure_tracking(session, job.id)
    tr.contact = lab.get("professor") or None
    session.add(tr)
    session.commit()
    return RedirectResponse(f"/?view=labs&added={job.id}", status_code=303)


def _clean_iso(value: str | None, fmt: str) -> str | None:
    from datetime import datetime

    try:
        return datetime.strptime((value or "").strip(), fmt).strftime(fmt)
    except ValueError:
        return None


def _add_event(request: Request, session: Session, url: str, description: str, form: dict):
    """Event entry (career fair, workshop, info session): fetch (or take the pasted text), extract the
    event, host, date, time, place and registration deadline, insert. No screening; starts as New."""
    from src.ingest.url_fetch import extract_event, fetch_event_page

    ev = extract_event(description, pasted=True) if description else fetch_event_page(url)
    if ev is None:
        return _render_board(request, session, add_form={**form, "needs_description": True})
    raw = build_job(url, description=ev["description"], title=ev.get("event") or "Event",
                    company=ev.get("host") or "Unknown host", location=ev.get("location") or None)
    job = create_manual_job(session, raw)
    job.kind, job.lane = "event", None
    job.event_date, job.event_time = _clean_iso(ev.get("date"), "%Y-%m-%d"), _clean_iso(ev.get("time"), "%H:%M")
    job.deadline = _clean_iso(ev.get("registration_deadline"), "%Y-%m-%d")
    session.add(job)
    session.commit()
    return RedirectResponse(f"/?view=events&added={job.id}", status_code=303)


@router.post("/jobs/add")
def add_job(
    request: Request,
    session: Session = Depends(get_session),
    url: str = Form(...),
    description: str = Form(""),
    kind: str = Form("job"),
):
    """Same steps as scripts/add_manual_job.py + `run --job-id`, behind a form:
    dedupe -> auto-fetch (unless a description was pasted) -> insert -> screen.
    kind=outreach adds a lab outreach entry instead (no screening)."""
    url, description = url.strip(), description.strip()
    form = {"url": url, "description": description, "kind": kind}
    if not url:
        return _render_board(request, session, add_form={**form, "error": "Paste a URL first."})

    if is_duplicate(session, url):
        existing = session.get(Job, url_job_id(url))
        return _render_board(request, session, add_form={**form, "duplicate": existing})

    if kind == "outreach":
        return _add_lab(request, session, url, description, form)
    if kind == "event":
        return _add_event(request, session, url, description, form)

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

    enrich_and_match(session, job)  # role card + archetype first, so screening can use the archetype; never blocks

    try:
        session.add(screen_job(job, archetype_text(session, job.id)))
        session.add(job)  # screen_job backfills title/company from the description
        session.commit()
    except Exception as exc:  # the job is saved either way; screening can be re-run from the CLI
        session.rollback()
        return _render_board(
            request, session, add_form={"error": f"Added the job, but screening failed: {exc}"}
        )

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


@router.post("/jobs/{job_id}/bookmark")
def set_bookmark(job_id: str, session: Session = Depends(get_session), value: str = Form(...)):
    """Bookmark on/off (board card star)."""
    job = session.get(Job, job_id)
    if job is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    job.bookmarked = value == "1"
    session.add(job)
    session.commit()
    return JSONResponse({"bookmarked": job.bookmarked})
