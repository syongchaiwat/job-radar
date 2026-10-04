"""Per-archetype market stats (docs/pipeline-revamp.md §5.4), computed
deterministically from market-data jobs in the active archetype set."""
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from src.db import Archetype, ArchetypeSet, Job, JobArchetype, JobSkill, ProfileTerm, RoleCard, Skill
from src.market.evidence import evidence, profile_terms

RECENT_DAYS = 180
GAP_MIN_SHARE = 0.15  # a skill counts as a gap worth listing if at least this share of jobs asks for it


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _language(raw: str) -> str:
    return re.split(r"[\s(:,-]", raw.strip(), maxsplit=1)[0].capitalize() if raw.strip() else "?"


def active_set(session: Session) -> ArchetypeSet | None:
    return session.exec(select(ArchetypeSet).where(ArchetypeSet.status == "active")).first()


def market_overview(session: Session, refresh_evidence: bool = True) -> dict:
    aset = active_set(session)
    if aset is None:
        return {"set": None, "archetypes": []}
    ev = evidence(session, refresh=refresh_evidence)
    terms = profile_terms()
    term_rows = {r.term: json.loads(r.skill_ids) for r in session.exec(select(ProfileTerm)).all()}
    terms_for: dict[int, list[str]] = {}
    for term, ids in term_rows.items():
        if term in terms:
            for sid in ids:
                terms_for.setdefault(sid, []).append(term)
    skills = {s.id: s for s in session.exec(select(Skill)).all()}
    archetypes = session.exec(select(Archetype).where(Archetype.set_version == aset.version)).all()
    rows = session.exec(
        select(JobArchetype, Job, RoleCard)
        .where(JobArchetype.set_version == aset.version, JobArchetype.role == "primary",
               JobArchetype.job_id == Job.id, Job.id == RoleCard.job_id, Job.market_data == True)  # noqa: E712
    ).all()
    links: dict[str, list[JobSkill]] = {}
    for link in session.exec(select(JobSkill)).all():
        links.setdefault(link.job_id, []).append(link)
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)

    out = []
    for a in archetypes:
        members = [(job, card) for ja, job, card in rows if ja.archetype_id == a.id]
        n = len(members)
        recent = [job for job, _ in members if _as_utc(job.posted_at or job.first_seen) >= cutoff]
        req, nice, rec = Counter(), Counter(), Counter()
        recent_ids = {j.id for j in recent}
        for job, _ in members:
            for link in links.get(job.id, []):
                (req if link.importance == "required" else nice)[link.skill_id] += 1
                if job.id in recent_ids:
                    rec[link.skill_id] += 1
        demand = []
        for sid in set(req) | set(nice):
            total = req[sid] + nice[sid]
            sk = skills.get(sid)
            if sk is None:
                continue
            demand.append({
                "skill": sk.name, "skill_id": sid, "category": sk.category, "jobs": total,
                "share": total / n if n else 0, "required": req[sid], "nice": nice[sid],
                "recent_share": rec[sid] / len(recent) if recent else None,
                "evidenced": sid in ev, "sources": sorted(ev.get(sid, set())), "terms": sorted(terms_for.get(sid, [])),
            })
        demand.sort(key=lambda d: (-d["jobs"], -d["required"], d["skill"].lower()))
        weight = sum(d["share"] for d in demand)
        covered = sum(d["share"] for d in demand if d["evidenced"])
        gaps = [d for d in demand if not d["evidenced"] and d["share"] >= GAP_MIN_SHARE]
        strengths = [d for d in demand if d["evidenced"] and d["share"] >= GAP_MIN_SHARE]
        langs = Counter()
        for _, card in members:
            for raw in json.loads(card.languages_required or "[]"):
                langs[_language(raw)] += 1
        out.append({
            "archetype": a, "n": n, "n_recent": len(recent), "demand": demand,
            "coverage": round(covered / weight, 2) if weight else None,
            "strengths": strengths, "gaps": gaps,
            "levels": Counter(card.level for _, card in members).most_common(),
            "lanes": Counter(json.loads(card.lane_signals or "{}").get("employment_type") or "unclear" for _, card in members).most_common(),
            "languages": langs.most_common(6),
            "domains": Counter((card.domain or "-").lower() for _, card in members).most_common(6),
            "jobs": sorted(((job, card) for job, card in members), key=lambda jc: jc[0].title.lower()),
        })
    out.sort(key=lambda r: -r["n"])
    return {"set": aset, "archetypes": out, "n_evidenced": len(ev)}
