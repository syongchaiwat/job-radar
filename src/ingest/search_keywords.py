"""Search keywords per archetype, generated from the data (no hand-written list).

For each archetype in the active set: the most common normalized job titles
among its market-data jobs. Confirming a new archetype set changes the queries
automatically.
"""
from collections import Counter

from sqlmodel import Session, select

from src.db import Archetype, ArchetypeSet, Job, JobArchetype, RoleCard

TITLES_PER_ARCHETYPE = 6


def load_search_keywords(session: Session) -> dict[str, list[str]]:
    """Return {archetype slug: [job-title keywords]}."""
    aset = session.exec(select(ArchetypeSet).where(ArchetypeSet.status == "active")).first()
    if aset is None:
        return {}
    out: dict[str, list[str]] = {}
    for a in session.exec(select(Archetype).where(Archetype.set_version == aset.version)).all():
        rows = session.exec(
            select(RoleCard.title_normalized)
            .join(JobArchetype, JobArchetype.job_id == RoleCard.job_id)
            .join(Job, Job.id == RoleCard.job_id)
            .where(JobArchetype.archetype_id == a.id, JobArchetype.role == "primary", Job.market_data == True)  # noqa: E712
        ).all()
        out[a.slug] = [t for t, _ in Counter(r for r in rows if r).most_common(TITLES_PER_ARCHETYPE)]
    return out
