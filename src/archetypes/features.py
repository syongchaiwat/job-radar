"""Shared inputs for assignment and clustering: role cards, vectors, skills."""
import json
import math
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from sqlmodel import Session, select

from src.db import Embedding, Job, JobSkill, RoleCard, Skill
from src.enrich.embeddings import from_bytes


@dataclass
class PoolJob:
    job_id: str
    title: str
    company: str
    card: RoleCard
    vec: np.ndarray
    required: list[str] = field(default_factory=list)
    nice: list[str] = field(default_factory=list)

    @property
    def lane(self) -> str:
        return json.loads(self.card.lane_signals or "{}").get("employment_type") or "unclear"


def load_jobs(session: Session, job_ids: list[str] | None = None, market_only: bool = False) -> list[PoolJob]:
    """Jobs that have both a role card and an embedding."""
    q = select(Job, RoleCard, Embedding).where(Job.id == RoleCard.job_id, Job.id == Embedding.job_id)
    if market_only:
        q = q.where(Job.market_data == True)  # noqa: E712
    rows = session.exec(q).all()
    wanted = set(job_ids) if job_ids is not None else None
    skills: dict[str, dict[str, list[str]]] = {}
    for link, sk in session.exec(select(JobSkill, Skill).where(JobSkill.skill_id == Skill.id)).all():
        skills.setdefault(link.job_id, {"required": [], "nice_to_have": []}).setdefault(link.importance, []).append(sk.name)
    out = []
    for job, card, emb in rows:
        if wanted is not None and job.id not in wanted:
            continue
        s = skills.get(job.id, {})
        out.append(PoolJob(job.id, job.title or card.title_normalized, job.company or "", card, from_bytes(emb.vector),
                           sorted(s.get("required", [])), sorted(s.get("nice_to_have", []))))
    out.sort(key=lambda p: p.job_id)
    return out


def skill_idf(pool: list[PoolJob]) -> dict[str, float]:
    df = Counter()
    for pj in pool:
        df.update(set(pj.required) | set(pj.nice))
    n = max(len(pool), 1)
    return {s: math.log((n + 1) / (c + 1)) + 1.0 for s, c in df.items()}


def skill_weights(pj: PoolJob, idf: dict[str, float]) -> dict[str, float]:
    """Required skills count fully, nice-to-haves half; rare skills weigh more (IDF)."""
    w = {s: idf.get(s, 1.0) for s in pj.required}
    for s in pj.nice:
        w.setdefault(s, 0.5 * idf.get(s, 1.0))
    return w


def cosine_dict(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0.0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def skill_matrix(pool: list[PoolJob], idf: dict[str, float]) -> np.ndarray:
    vocab = sorted(idf)
    index = {s: i for i, s in enumerate(vocab)}
    m = np.zeros((len(pool), len(vocab)), dtype=np.float32)
    for r, pj in enumerate(pool):
        for s, w in skill_weights(pj, idf).items():
            if s in index:
                m[r, index[s]] = w
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return m / norms


def combined_matrix(pool: list[PoolJob], idf: dict[str, float], skill_weight: float = 0.35) -> np.ndarray:
    """Role-card embedding plus a down-weighted skill vector: semantic similarity
    with a nudge toward shared concrete skills."""
    dense = np.vstack([pj.vec for pj in pool])
    sk = skill_matrix(pool, idf)
    return np.hstack([dense * (1 - skill_weight), sk * skill_weight]).astype(np.float32)


def compact_card(pj: PoolJob, max_summary: int = 260) -> str:
    """One-line role card for LLM prompts."""
    summary = pj.card.summary.strip().replace("\n", " ")
    if len(summary) > max_summary:
        summary = summary[:max_summary].rsplit(" ", 1)[0] + "…"
    skills = ", ".join(pj.required[:12])
    extra = f"; nice: {', '.join(pj.nice[:6])}" if pj.nice else ""
    return (f"[{pj.job_id}] {pj.card.title_normalized} | {pj.card.domain or '-'} | level {pj.card.level} | "
            f"{pj.lane} | {summary} | skills: {skills}{extra}")


def top_skills(pool: list[PoolJob], n: int = 10) -> list[tuple[str, int]]:
    c = Counter()
    for pj in pool:
        c.update(set(pj.required) | set(pj.nice))
    return c.most_common(n)
