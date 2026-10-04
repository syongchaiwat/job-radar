"""Skill dictionary: map extracted skill names to canonical Skill rows.

Lookup order: alias table (lowercase) -> canonical name (case-insensitive) ->
create a new 'pending' skill for review on the Skills page. Merging skills
turns the merged name into an alias, so future extractions resolve to the
survivor without an LLM call.
"""
from sqlalchemy import func
from sqlmodel import Session, select

from src.db import JobSkill, Skill, SkillAlias


def known_skills_prompt(session: Session, limit: int = 500) -> str:
    """Approved skills first, then pending ones, as 'Name (category)'."""
    rows = session.exec(select(Skill).order_by(Skill.status, Skill.name)).all()
    approved = [s for s in rows if s.status == "approved"]
    pending = [s for s in rows if s.status != "approved"]
    picked = (approved + pending)[:limit]
    if not picked:
        return "(none yet: propose short conventional names)"
    return ", ".join(f"{s.name} ({s.category})" for s in picked)


def resolve_skill(session: Session, name: str, category: str = "other") -> Skill:
    clean = " ".join(name.split()).strip()
    low = clean.lower()
    alias = session.get(SkillAlias, low)
    if alias:
        return session.get(Skill, alias.skill_id)
    existing = session.exec(select(Skill).where(func.lower(Skill.name) == low)).first()
    if existing:
        return existing
    skill = Skill(name=clean, category=category, status="pending")
    session.add(skill)
    session.flush()
    return skill


def merge_skills(session: Session, source_ids: list[int], target_id: int) -> None:
    """Fold source skills into target: job links move over, names become aliases."""
    target = session.get(Skill, target_id)
    for sid in source_ids:
        if sid == target_id:
            continue
        src = session.get(Skill, sid)
        if src is None:
            continue
        for link in session.exec(select(JobSkill).where(JobSkill.skill_id == sid)).all():
            dup = session.get(JobSkill, (link.job_id, target_id))
            if dup is None:
                session.add(JobSkill(job_id=link.job_id, skill_id=target_id, importance=link.importance, raw_term=link.raw_term))
            elif link.importance == "required":
                dup.importance = "required"
                session.add(dup)
            session.delete(link)
        for alias in session.exec(select(SkillAlias).where(SkillAlias.skill_id == sid)).all():
            alias.skill_id = target_id
            session.add(alias)
        if src.name.lower() != target.name.lower() and session.get(SkillAlias, src.name.lower()) is None:
            session.add(SkillAlias(alias=src.name.lower(), skill_id=target_id))
        session.flush()
        session.delete(src)
    session.flush()


def job_skill_names(session: Session, job_id: str) -> dict[str, list[str]]:
    links = session.exec(select(JobSkill, Skill).where(JobSkill.job_id == job_id, JobSkill.skill_id == Skill.id)).all()
    out = {"required": [], "nice_to_have": []}
    for link, skill in links:
        out.setdefault(link.importance, []).append(skill.name)
    for k in out:
        out[k].sort(key=str.lower)
    return out
