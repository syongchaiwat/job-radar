"""Single-job assignment to existing archetypes (docs/pipeline-revamp.md §5.2).

Three scores per archetype, combined:
  1. centroid similarity: job embedding vs the mean of member embeddings
  2. nearest neighbors:   mean similarity to the k most similar members
  3. skill overlap:       IDF-weighted skill cosine vs the archetype's skill profile
A clear winner (score and margin over the runner-up above calibrated thresholds)
is assigned directly with no LLM call; anything else goes to LLM adjudication.
"""
from dataclasses import dataclass, field

import numpy as np

from src.archetypes.features import PoolJob, cosine_dict, skill_weights
from src.llm.call import call, load_prompt
from src.llm.schemas import ArchetypeAdjudication

W_CENTROID, W_KNN, W_SKILL = 0.4, 0.3, 0.3
KNN_K = 5
DEFAULT_THRESHOLDS = {"abs": 0.62, "margin": 0.03}  # replaced by calibrate() whenever labels exist
SECONDARY_GAP = 0.015


@dataclass
class Profile:
    key: str  # slug (draft proposals) or str(archetype id) (confirmed sets)
    name: str
    definition: str
    include: str = ""
    exclude: str = ""
    defining_skills: list[str] = field(default_factory=list)
    members: list[PoolJob] = field(default_factory=list)
    centroid: np.ndarray | None = None
    skill_profile: dict[str, float] = field(default_factory=dict)


def build_profiles(profiles: list[Profile], idf: dict[str, float]) -> list[Profile]:
    for p in profiles:
        if p.members:
            c = np.mean([m.vec for m in p.members], axis=0)
            p.centroid = c / (np.linalg.norm(c) or 1.0)
            agg: dict[str, float] = {}
            for m in p.members:
                for s, w in skill_weights(m, idf).items():
                    agg[s] = agg.get(s, 0.0) + w
            p.skill_profile = {s: w / len(p.members) for s, w in agg.items()}
        else:
            p.centroid, p.skill_profile = None, {s: 1.0 for s in p.defining_skills}
    return profiles


def score(pj: PoolJob, p: Profile, idf: dict[str, float], exclude_self: bool = True) -> dict:
    members = [m for m in p.members if not (exclude_self and m.job_id == pj.job_id)]
    if members:
        if exclude_self and len(members) != len(p.members):  # leave-one-out centroid
            c = np.mean([m.vec for m in members], axis=0)
            c = c / (np.linalg.norm(c) or 1.0)
        else:
            c = p.centroid
        centroid = float(pj.vec @ c)
        sims = sorted((float(pj.vec @ m.vec) for m in members), reverse=True)
        knn = float(np.mean(sims[:KNN_K]))
        prof = p.skill_profile if len(members) == len(p.members) else _skill_profile(members, idf)
    else:
        centroid = knn = 0.0
        prof = p.skill_profile
    skill = cosine_dict(skill_weights(pj, idf), prof)
    total = W_CENTROID * centroid + W_KNN * knn + W_SKILL * skill
    return {"key": p.key, "score": total, "centroid": centroid, "knn": knn, "skill": skill}


def _skill_profile(members: list[PoolJob], idf: dict[str, float]) -> dict[str, float]:
    agg: dict[str, float] = {}
    for m in members:
        for s, w in skill_weights(m, idf).items():
            agg[s] = agg.get(s, 0.0) + w
    return {s: w / len(members) for s, w in agg.items()}


def rank(pj: PoolJob, profiles: list[Profile], idf: dict[str, float], exclude_self: bool = True) -> list[dict]:
    return sorted((score(pj, p, idf, exclude_self) for p in profiles), key=lambda r: -r["score"])


def is_clear(ranked: list[dict], thresholds: dict) -> bool:
    if not ranked:
        return False
    top = ranked[0]["score"]
    second = ranked[1]["score"] if len(ranked) > 1 else 0.0
    return top >= thresholds["abs"] and (top - second) >= thresholds["margin"]


def matched_skills(pj: PoolJob, p: Profile, n: int = 5) -> list[str]:
    mine = set(pj.required) | set(pj.nice)
    return [s for s, _ in sorted(p.skill_profile.items(), key=lambda kv: -kv[1]) if s in mine][:n]


def calibrate(profiles: list[Profile], idf: dict[str, float], target_precision: float = 0.95) -> dict:
    """Pick thresholds on known members (leave-one-out) so the direct path is right
    >= target_precision of the time, maximizing how many jobs it covers."""
    rows = []
    for p in profiles:
        for m in p.members:
            ranked = rank(m, profiles, idf, exclude_self=True)
            if len(ranked) < 2:
                continue
            rows.append((ranked[0]["score"], ranked[0]["score"] - ranked[1]["score"], ranked[0]["key"] == p.key))
    if len(rows) < 10:
        return dict(DEFAULT_THRESHOLDS, calibrated=False, n=len(rows))
    best = None
    for t_abs in np.arange(0.50, 0.86, 0.01):
        for t_margin in np.arange(0.0, 0.081, 0.005):
            hits = [ok for s, mg, ok in rows if s >= t_abs and mg >= t_margin]
            if len(hits) < 5:
                continue
            precision = sum(hits) / len(hits)
            if precision >= target_precision and (best is None or len(hits) > best[2]):
                best = (round(float(t_abs), 3), round(float(t_margin), 3), len(hits), precision)
    if best is None:
        return dict(DEFAULT_THRESHOLDS, calibrated=False, n=len(rows))
    return {"abs": best[0], "margin": best[1], "calibrated": True, "n": len(rows),
            "coverage": round(best[2] / len(rows), 3), "precision": round(best[3], 3)}


def adjudicate(pj: PoolJob, candidates: list[Profile]) -> ArchetypeAdjudication:
    """LLM picks among the top candidates (or 'none') for uncertain or thin postings."""
    blocks = []
    for p in candidates:
        examples = "\n".join(f"    - {m.card.title_normalized} ({m.card.domain or '-'})" for m in p.members[:3])
        blocks.append(
            f"### {p.key}: {p.name}\nDefinition: {p.definition}\nInclude: {p.include or '-'}\nExclude: {p.exclude or '-'}\n"
            f"Defining skills: {', '.join(p.defining_skills) or '-'}\nExample members:\n{examples or '    (none yet)'}"
        )
    from src.archetypes.features import compact_card

    prompt = load_prompt("archetypes/adjudicate").format(candidates="\n\n".join(blocks), job=compact_card(pj, max_summary=600))
    parsed, _log = call("deep", prompt, ArchetypeAdjudication, method="json_schema")
    return parsed


def assign(pj: PoolJob, profiles: list[Profile], idf: dict[str, float], thresholds: dict, use_llm: bool = True) -> dict:
    """Returns {key, method, score, confidence, rationale, secondary} for one job."""
    ranked = rank(pj, profiles, idf, exclude_self=True)
    if not ranked:
        return {"key": None, "method": "none"}
    by_key = {p.key: p for p in profiles}
    top = ranked[0]
    secondary = None
    if len(ranked) > 1 and top["score"] - ranked[1]["score"] <= SECONDARY_GAP and ranked[1]["score"] >= thresholds["abs"]:
        secondary = ranked[1]["key"]
    if is_clear(ranked, thresholds) or not use_llm:
        skills = matched_skills(pj, by_key[top["key"]])
        return {"key": top["key"], "method": "embedding", "score": top["score"],
                "confidence": min(1.0, 0.5 + (top["score"] - (ranked[1]["score"] if len(ranked) > 1 else 0)) * 5),
                "rationale": ("matched " + ", ".join(skills)) if skills else "closest by role similarity",
                "secondary": secondary, "ranked": ranked[:3]}
    candidates = [by_key[r["key"]] for r in ranked[:3]]
    verdict = adjudicate(pj, candidates)
    key = verdict.archetype if verdict.archetype in by_key else None
    return {"key": key, "method": "llm", "score": next((r["score"] for r in ranked if r["key"] == key), None),
            "confidence": verdict.confidence, "rationale": verdict.rationale,
            "secondary": verdict.secondary if verdict.secondary in by_key and verdict.secondary != key else None,
            "ranked": ranked[:3]}
