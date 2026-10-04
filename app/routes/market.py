"""Market page: GET /market, POST /market/suggest/{archetype_id}, POST /market/todo,
POST /market/todo/{id}/toggle, POST /market/todo/{id}/delete, POST /market/evidence/remove"""
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from app.deps import get_session
from app.templating import templates
from src.db import Archetype, MarketSuggestion, MarketTodo, ProfileTerm
from src.market.stats import market_overview
from src.pipeline import profile_context as pc
from src.pipeline.llm_call import call, load_prompt
from src.pipeline.schemas import NextSteps

router = APIRouter()


@router.get("/market")
def market_page(request: Request, a: str | None = None, session: Session = Depends(get_session)):
    overview = market_overview(session)
    rows = overview["archetypes"]
    current = next((r for r in rows if str(r["archetype"].id) == a), rows[0] if rows else None)
    suggestion = todos = None
    if current:
        sug = session.get(MarketSuggestion, current["archetype"].id)
        suggestion = json.loads(sug.suggestions) if sug else None
        todos = session.exec(select(MarketTodo).where(MarketTodo.archetype_slug == current["archetype"].slug).order_by(MarketTodo.done, MarketTodo.id)).all()
    return templates.TemplateResponse(
        request=request, name="market.html",
        context={"overview": overview, "rows": rows, "current": current, "suggestion": suggestion,
                 "suggestion_row": session.get(MarketSuggestion, current["archetype"].id) if current else None, "todos": todos},
    )


@router.post("/market/suggest/{archetype_id}")
def suggest(archetype_id: int, session: Session = Depends(get_session)):
    overview = market_overview(session, refresh_evidence=False)
    row = next((r for r in overview["archetypes"] if r["archetype"].id == archetype_id), None)
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown archetype")
    a = row["archetype"]
    projects = "\n".join(
        line for line in pc.load_projects().splitlines() if line.startswith("## ") or line.startswith("- **Tools:**")
    )
    prompt = load_prompt("market_suggestions").format(
        archetype=f"{a.name}: {a.definition}",
        demand="\n".join(f"- {d['skill']}: {round(d['share'] * 100)}% ({d['jobs']} of {row['n']})" for d in row["demand"][:25]),
        gaps="\n".join(f"- {d['skill']}: {round(d['share'] * 100)}%" for d in row["gaps"]) or "(none above the threshold)",
        projects=projects,
    )
    parsed, _ = call("deep", prompt, NextSteps, method="json_schema")
    sug = session.get(MarketSuggestion, archetype_id) or MarketSuggestion(archetype_id=archetype_id)
    sug.suggestions = json.dumps([s.model_dump() for s in parsed.steps])
    sug.created_at = datetime.now(timezone.utc)
    session.add(sug)
    session.commit()
    return RedirectResponse(f"/market?a={archetype_id}#next-steps", status_code=303)


@router.post("/market/todo")
def add_todo(session: Session = Depends(get_session), archetype_id: int = Form(...), text: str = Form(...)):
    a = session.get(Archetype, archetype_id)
    if a is None or not text.strip():
        return RedirectResponse(f"/market?a={archetype_id}", status_code=303)
    session.add(MarketTodo(archetype_slug=a.slug, text=text.strip()))
    session.commit()
    return RedirectResponse(f"/market?a={archetype_id}#todos", status_code=303)


@router.post("/market/todo/{todo_id}/toggle")
def toggle_todo(todo_id: int, session: Session = Depends(get_session), archetype_id: int = Form(...)):
    t = session.get(MarketTodo, todo_id)
    if t:
        t.done = not t.done
        session.add(t)
        session.commit()
    return RedirectResponse(f"/market?a={archetype_id}#todos", status_code=303)


@router.post("/market/todo/{todo_id}/delete")
def delete_todo(todo_id: int, session: Session = Depends(get_session), archetype_id: int = Form(...)):
    t = session.get(MarketTodo, todo_id)
    if t:
        session.delete(t)
        session.commit()
    return RedirectResponse(f"/market?a={archetype_id}#todos", status_code=303)


@router.post("/market/evidence/remove")
def remove_evidence(session: Session = Depends(get_session), term: str = Form(...), skill_id: int = Form(...), archetype_id: int = Form(...)):
    """'Not evidence': drop one term -> skill mapping (kept as a user decision)."""
    row = session.get(ProfileTerm, term)
    if row:
        ids = [i for i in json.loads(row.skill_ids) if i != skill_id]
        row.skill_ids, row.method = json.dumps(ids), "user"
        session.add(row)
        session.commit()
    return RedirectResponse(f"/market?a={archetype_id}#strengths", status_code=303)


@router.post("/market/export-notes")
def export_notes_now(session: Session = Depends(get_session)):
    from src.archetypes.commit import export_notes
    from src.market.stats import active_set

    aset = active_set(session)
    if aset:
        export_notes(session, aset.version)
    return RedirectResponse("/market?exported=1", status_code=303)
