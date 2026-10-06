"""Skill dictionary review: GET /skills, POST /skills/approve, POST /skills/merge, POST /skills/{id}/edit"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlmodel import Session, select

from app.deps import get_session
from app.templating import templates
from src.db import JobSkill, Skill, SkillAlias
from src.enrich.skills import merge_skills
from src.llm.schemas import SkillCategory

router = APIRouter()
CATEGORIES = list(SkillCategory.__args__)


@router.get("/skills")
def skills_page(request: Request, status: str = "pending", session: Session = Depends(get_session)):
    counts: dict[int, list[int]] = {}
    raw_terms: dict[int, set[str]] = {}
    for link in session.exec(select(JobSkill)).all():
        c = counts.setdefault(link.skill_id, [0, 0])
        c[0 if link.importance == "required" else 1] += 1
        if link.raw_term:
            raw_terms.setdefault(link.skill_id, set()).add(link.raw_term)
    aliases: dict[int, list[str]] = {}
    for a in session.exec(select(SkillAlias)).all():
        aliases.setdefault(a.skill_id, []).append(a.alias)

    all_skills = session.exec(select(Skill)).all()
    shown = [s for s in all_skills if status == "all" or s.status == status]
    rows = sorted(
        (
            {
                "skill": s,
                "required": counts.get(s.id, (0, 0))[0],
                "nice": counts.get(s.id, (0, 0))[1],
                "raw_terms": sorted(raw_terms.get(s.id, set()), key=str.lower)[:6],
                "aliases": sorted(aliases.get(s.id, [])),
            }
            for s in shown
        ),
        key=lambda r: (-(r["required"] + r["nice"]), r["skill"].name.lower()),
    )
    return templates.TemplateResponse(
        request=request,
        name="skills.html",
        context={
            "rows": rows,
            "status": status,
            "categories": CATEGORIES,
            "all_skills": sorted(all_skills, key=lambda s: s.name.lower()),
            "n_pending": sum(s.status == "pending" for s in all_skills),
            "n_approved": sum(s.status == "approved" for s in all_skills),
        },
    )


@router.post("/skills/approve")
def approve(session: Session = Depends(get_session), skill_ids: list[int] = Form(...), status: str = Form("pending")):
    for sid in skill_ids:
        skill = session.get(Skill, sid)
        if skill:
            skill.status = "approved"
            session.add(skill)
    session.commit()
    return RedirectResponse(f"/skills?status={status}", status_code=303)


@router.post("/skills/merge")
def merge(
    session: Session = Depends(get_session),
    skill_ids: list[int] = Form(...),
    target_id: int = Form(...),
    status: str = Form("pending"),
):
    target = session.get(Skill, target_id)
    if target is None:
        raise HTTPException(status_code=400, detail="Unknown merge target")
    merge_skills(session, [s for s in skill_ids if s != target_id], target_id)
    target.status = "approved"
    session.add(target)
    session.commit()
    return RedirectResponse(f"/skills?status={status}", status_code=303)


@router.post("/skills/{skill_id}/edit")
def edit(
    skill_id: int,
    session: Session = Depends(get_session),
    name: str = Form(...),
    category: str = Form(...),
    status: str = Form("pending"),
):
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    name = " ".join(name.split())
    clash = session.exec(select(Skill).where(func.lower(Skill.name) == name.lower(), Skill.id != skill_id)).first()
    if clash:  # renaming onto an existing skill = merging into it
        merge_skills(session, [skill_id], clash.id)
    else:
        old = skill.name
        skill.name = name
        skill.category = category if category in CATEGORIES else "other"
        skill.status = "approved"
        session.add(skill)
        if old.lower() != name.lower() and session.get(SkillAlias, old.lower()) is None:
            session.add(SkillAlias(alias=old.lower(), skill_id=skill_id))
    session.commit()
    return RedirectResponse(f"/skills?status={status}", status_code=303)
