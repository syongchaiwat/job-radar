"""Archetype rework orchestration (docs/pipeline-revamp.md §5.3).

Market-data jobs -> refresh outdated role cards -> Track 1 (stable clustering)
and Track 2 (LLM taxonomy) -> reconcile (Opus) -> consistency check (single-job
assignment, leave-one-out) -> quality signals + 2D map -> draft proposal stored
on a ClassifyRun for review on the Classify page.

Proposal JSON:
  jobs: {job_id: {title, company, lane, quality, x, y, t1, t2, t2_conf, check, flagged}}
  archetypes: [{key, name, definition, include, exclude, defining_skills,
                maps_from: [current archetype ids], members: [job_ids], stats: {...}}]
  unassigned: [job_ids]
  taxonomy, clusters, notes, summary, thresholds
"""
import json
import re
from collections import Counter
from datetime import datetime, timezone

import numpy as np
from sklearn.metrics import adjusted_rand_score
from sqlmodel import Session, select

from src.archetypes import track1, track2
from src.archetypes.assign import Profile, build_profiles, calibrate, rank
from src.archetypes.features import PoolJob, combined_matrix, compact_card, load_jobs, skill_idf, top_skills
from src.db import Archetype, ArchetypeSet, ClassifyRun, Job, RoleCard
from src.enrich import enrich_job
from src.enrich.enrich import ROLE_CARD_PROMPT_VERSION
from src.pipeline.llm_call import call, load_prompt
from src.pipeline.schemas import Reconciliation, SplitNaming

SMALL_POOL = 40


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "archetype"


def active_set(session: Session) -> ArchetypeSet | None:
    return session.exec(select(ArchetypeSet).where(ArchetypeSet.status == "active")).first()


def current_archetypes(session: Session) -> list[Archetype]:
    s = active_set(session)
    if s is None:
        return []
    return session.exec(select(Archetype).where(Archetype.set_version == s.version)).all()


def outdated_cards(session: Session) -> list[str]:
    rows = session.exec(select(Job.id, RoleCard.prompt_version).where(Job.id == RoleCard.job_id, Job.market_data == True)).all()  # noqa: E712
    return [jid for jid, v in rows if v != ROLE_CARD_PROMPT_VERSION]


def _crosstab(pool: list[PoolJob], t1: np.ndarray, t2: dict[str, tuple[str, float]]) -> str:
    names = sorted({lab for lab, _ in t2.values()})
    table = Counter((int(t1[i]), t2[pj.job_id][0]) for i, pj in enumerate(pool))
    header = "cluster | " + " | ".join(names)
    rows = [header]
    for c in sorted(set(int(x) for x in t1)):
        label = "outliers" if c < 0 else f"C{c}"
        rows.append(f"{label} | " + " | ".join(str(table.get((c, n), 0)) for n in names))
    return "\n".join(rows)


def _clusters_text(pool: list[PoolJob], t1: dict) -> str:
    out = []
    labels = t1["labels"]
    for c in sorted(set(int(x) for x in labels if x >= 0)):
        mem = [pj for pj, l in zip(pool, labels) if l == c]
        skills = ", ".join(f"{s} ({n})" for s, n in top_skills(mem, 10))
        titles = "; ".join(m.card.title_normalized for m in mem[:12])
        out.append(f"C{c}: {len(mem)} jobs, stability {t1['stability'][c]}\n  top skills: {skills}\n  titles: {titles}")
    return "\n\n".join(out) or "(no stable clusters)"


def _current_text(archetypes: list[Archetype]) -> str:
    if not archetypes:
        return "(none: this is the first rework)"
    return "\n".join(f"- {a.name}: {a.definition}" for a in archetypes)


def build_proposal(session: Session, progress=lambda msg: None) -> tuple[dict, int]:
    tokens = 0
    for jid in outdated_cards(session):  # only cards on an older prompt version get re-extracted
        progress(f"Refreshing outdated role card {jid}")
        enrich_job(session, session.get(Job, jid), force=True)
        session.commit()

    pool = load_jobs(session, market_only=True)
    if len(pool) < 6:
        raise ValueError(f"Only {len(pool)} market-data jobs with role cards; mark more jobs as market data first.")
    idf = skill_idf(pool)
    x = combined_matrix(pool, idf)

    progress("Track 1: stable clustering")
    t1 = track1.run(x, progress)
    progress("Track 2: building taxonomy")
    taxonomy, tk = track2.build_taxonomy(pool, progress)
    tokens += tk
    t2_labels, tk = track2.label_jobs(pool, taxonomy, progress)
    tokens += tk

    progress("Reconciling the two tracks (Opus)")
    current = current_archetypes(session)
    outliers = [compact_card(pj) for pj, l in zip(pool, t1["labels"]) if l < 0]
    prompt = load_prompt("archetype_reconcile").format(
        clusters=_clusters_text(pool, t1),
        taxonomy=track2.taxonomy_text(taxonomy),
        crosstab=_crosstab(pool, t1["labels"], t2_labels),
        outliers="\n".join(outliers) or "(none)",
        current=_current_text(current),
        cards="\n".join(compact_card(pj) for pj in pool),
    )
    rec, log = call("critique", prompt, Reconciliation)
    tokens += log.input_tokens + log.output_tokens

    progress("Consistency check and quality signals")
    proposal = assemble(pool, idf, t1, taxonomy, t2_labels, rec, current, x)
    return proposal, tokens


def assemble(pool, idf, t1, taxonomy, t2_labels, rec: Reconciliation, current: list[Archetype], x) -> dict:
    by_id = {pj.job_id: pj for pj in pool}
    keys = []
    archetypes = []
    for a in rec.archetypes:
        key = slugify(a.key or a.name)
        while key in keys:
            key += "-2"
        keys.append(key)
        current_ids = [c.id for c in current if c.name in a.maps_from]
        archetypes.append({
            "key": key, "name": a.name, "definition": a.definition, "include": a.include, "exclude": a.exclude,
            "defining_skills": a.defining_skills, "maps_from": current_ids, "from_clusters": a.from_clusters,
            "from_taxonomy": a.from_taxonomy, "members": [],
        })
    key_of = {a.key: k for a, k in zip(rec.archetypes, keys)} | {slugify(a.name): k for a, k in zip(rec.archetypes, keys)}
    assigned = {}
    for asg in rec.assignments:
        k = key_of.get(asg.archetype) or key_of.get(slugify(asg.archetype))
        if asg.job_id in by_id and k:
            assigned[asg.job_id] = k
    for a in archetypes:
        a["members"] = [jid for jid in sorted(assigned) if assigned[jid] == a["key"]]
    unassigned = [pj.job_id for pj in pool if pj.job_id not in assigned]

    coords = track1.layout_2d(x)
    jobs = {}
    for i, pj in enumerate(pool):
        lab, conf = t2_labels.get(pj.job_id, ("none", 0.0))
        jobs[pj.job_id] = {"title": pj.title, "company": pj.company, "lane": pj.lane,
                           "quality": pj.card.information_quality, "x": float(coords[i, 0]), "y": float(coords[i, 1]),
                           "t1": int(t1["labels"][i]), "t2": lab, "t2_conf": round(float(conf), 2)}
    proposal = {"jobs": jobs, "archetypes": archetypes, "unassigned": unassigned,
                "taxonomy": [a.model_dump() for a in taxonomy.archetypes], "taxonomy_changes": taxonomy.changes,
                "clusters": {str(c): s for c, s in t1["stability"].items()}, "notes": rec.notes}
    refresh_stats(proposal, pool, idf, t1)
    return proposal


def refresh_stats(proposal: dict, pool: list[PoolJob], idf: dict, t1: dict | None = None) -> None:
    """Recompute per-archetype quality signals, the consistency check and thresholds
    after the proposal is built or edited (rename/merge/split/move)."""
    by_id = {pj.job_id: pj for pj in pool}
    profiles = build_profiles([
        Profile(key=a["key"], name=a["name"], definition=a["definition"], include=a["include"], exclude=a["exclude"],
                defining_skills=a["defining_skills"], members=[by_id[j] for j in a["members"] if j in by_id])
        for a in proposal["archetypes"]
    ], idf)
    member_of = {j: a["key"] for a in proposal["archetypes"] for j in a["members"]}
    flagged = 0
    for jid, info in proposal["jobs"].items():
        pj = by_id.get(jid)
        if pj is None or not profiles:
            continue
        ranked = rank(pj, profiles, idf, exclude_self=True)
        info["check"] = ranked[0]["key"] if ranked else None
        info["flagged"] = bool(jid in member_of and ranked and ranked[0]["key"] != member_of[jid])
        flagged += info["flagged"]

    coassoc = t1["coassoc"] if t1 else None
    index = {pj.job_id: i for i, pj in enumerate(pool)}
    tax_for = {a["key"]: set(a.get("from_taxonomy", [])) for a in proposal["archetypes"]}
    cl_for = {a["key"]: set(a.get("from_clusters", [])) for a in proposal["archetypes"]}
    for a, p in zip(proposal["archetypes"], profiles):
        mem = [by_id[j] for j in a["members"] if j in by_id]
        stats = {"size": len(mem)}
        if mem and p.centroid is not None:
            stats["cohesion"] = round(float(np.mean([m.vec @ p.centroid for m in mem])), 3)
        if coassoc is not None and len(mem) > 1:
            ids = [index[m.job_id] for m in mem]
            pairs = coassoc[np.ix_(ids, ids)][np.triu_indices(len(ids), k=1)]
            stats["stability"] = round(float(pairs.mean()), 3)
        elif "stats" in a and "stability" in a["stats"]:
            stats["stability"] = a["stats"]["stability"]  # keep the original value after edits
        agree = [j for j in a["members"] if proposal["jobs"][j]["t2"] in tax_for[a["key"]] and proposal["jobs"][j]["t1"] in cl_for[a["key"]]]
        stats["tracks_agree"] = round(len(agree) / len(mem), 2) if mem else None
        stats["flagged"] = sum(proposal["jobs"][j].get("flagged", False) for j in a["members"])
        stats["top_skills"] = top_skills(mem, 8)
        stats["lanes"] = Counter(m.lane for m in mem).most_common()
        a["stats"] = stats

    t1_labels = [proposal["jobs"][pj.job_id]["t1"] for pj in pool]
    t2_labels = [proposal["jobs"][pj.job_id]["t2"] for pj in pool]
    proposal["summary"] = {
        "n_jobs": len(pool),
        "small_pool": len(pool) < SMALL_POOL,
        "tracks_ari": round(float(adjusted_rand_score(t1_labels, t2_labels)), 3) if len(pool) > 1 else None,
        "flagged": flagged,
        "unassigned": len(proposal["unassigned"]),
    }
    proposal["thresholds"] = calibrate(profiles, idf)


def start_run(session: Session) -> ClassifyRun:
    s = active_set(session)
    run = ClassifyRun(status="running", progress="Starting", base_version=s.version if s else None)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def execute(run_id: int, engine) -> None:
    """Background worker: builds the proposal and stores it on the run."""
    with Session(engine) as session:
        run = session.get(ClassifyRun, run_id)

        def progress(msg: str):
            run.progress = msg
            session.add(run)
            session.commit()

        try:
            proposal, tokens = build_proposal(session, progress)
            run.proposal = json.dumps(proposal)
            run.cost_tokens = tokens
            run.status = "draft"
            run.progress = "Ready for review"
        except Exception as exc:  # surfaced on the Classify page
            session.rollback()
            run = session.get(ClassifyRun, run_id)
            run.status = "failed"
            run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(timezone.utc)
        session.add(run)
        session.commit()


# --- edits on a draft proposal -------------------------------------------------

def load_proposal(run: ClassifyRun) -> dict:
    return json.loads(run.proposal or "{}")


def save_proposal(session: Session, run: ClassifyRun, proposal: dict) -> None:
    pool = load_jobs(session, list(proposal["jobs"]))
    refresh_stats(proposal, pool, skill_idf(pool))
    run.proposal = json.dumps(proposal)
    session.add(run)
    session.commit()


def edit_rename(proposal: dict, key: str, name: str, definition: str) -> None:
    for a in proposal["archetypes"]:
        if a["key"] == key:
            a["name"], a["definition"] = name.strip() or a["name"], definition.strip() or a["definition"]


def edit_move(proposal: dict, job_id: str, target: str) -> None:
    for a in proposal["archetypes"]:
        if job_id in a["members"]:
            a["members"].remove(job_id)
    if job_id in proposal["unassigned"]:
        proposal["unassigned"].remove(job_id)
    if target == "none":
        proposal["unassigned"].append(job_id)
        return
    for a in proposal["archetypes"]:
        if a["key"] == target:
            a["members"].append(job_id)
            a["members"].sort()


def _describe(session: Session, situation: str, sources: list[dict], member_ids: list[str]):
    """Sonnet writes one name/definition/criteria/skills covering every source and member."""
    from src.pipeline.schemas import ArchetypeDef

    pool = load_jobs(session, member_ids)
    src = "\n\n".join(
        f"- {a['name']}: {a['definition']}\n  include: {a.get('include', '')}\n  exclude: {a.get('exclude', '')}" for a in sources
    )
    prompt = load_prompt("archetype_merge").format(
        situation=situation, sources=src, cards="\n".join(compact_card(pj) for pj in pool) or "(no jobs)"
    )
    parsed, _ = call("deep", prompt, ArchetypeDef, method="json_schema")
    return parsed


def _apply_def(target: dict, d, name_override: str = "") -> None:
    target["name"] = name_override.strip() or d.name
    target["definition"], target["include"], target["exclude"] = d.definition, d.include, d.exclude
    target["defining_skills"] = d.defining_skills


def edit_merge(session: Session, proposal: dict, keys: list[str], name: str) -> None:
    keep = [a for a in proposal["archetypes"] if a["key"] in keys]
    if len(keep) < 2:
        return
    sources = [dict(a) for a in keep]
    first = keep[0]
    for other in keep[1:]:
        first["members"] = sorted(set(first["members"]) | set(other["members"]))
        first["maps_from"] = sorted(set(first["maps_from"]) | set(other["maps_from"]))
        first["from_clusters"] = sorted(set(first.get("from_clusters", [])) | set(other.get("from_clusters", [])))
        first["from_taxonomy"] = sorted(set(first.get("from_taxonomy", [])) | set(other.get("from_taxonomy", [])))
        proposal["archetypes"].remove(other)
    first["merged_from"] = [a["name"] for a in sources]
    d = _describe(session, f"It is the merge of {len(sources)} archetypes into one.", sources, first["members"])
    _apply_def(first, d, name)
    first["key"] = slugify(first["name"]) if not any(a is not first and a["key"] == slugify(first["name"]) for a in proposal["archetypes"]) else first["key"]


def edit_rewrite(session: Session, proposal: dict, key: str) -> None:
    """Regenerate name and description from the archetype's current jobs (e.g. after moves or an old merge)."""
    target = next((a for a in proposal["archetypes"] if a["key"] == key), None)
    if target is None:
        return
    sources = [dict(target)]
    situation = "Its jobs changed (moves or a merge), so its description must be rewritten to match them."
    if target.get("merged_from"):
        situation += f" It was formed by merging: {', '.join(target['merged_from'])}."
    _apply_def(target, _describe(session, situation, sources, target["members"]))


def edit_split(session: Session, proposal: dict, key: str) -> None:
    """Split one archetype in two: 2-means on member embeddings, the LLM names both parts."""
    from sklearn.cluster import KMeans

    target = next((a for a in proposal["archetypes"] if a["key"] == key), None)
    if target is None or len(target["members"]) < 4:
        raise ValueError("Need at least 4 jobs to split an archetype.")
    pool = load_jobs(session, target["members"])
    x = np.vstack([pj.vec for pj in pool])
    labels = KMeans(n_clusters=2, n_init=10, random_state=0).fit_predict(x)
    groups = [[pj for pj, l in zip(pool, labels) if l == g] for g in (0, 1)]
    prompt = load_prompt("archetype_split").format(
        n=2,
        archetype=f"{target['name']}: {target['definition']}",
        groups="\n\n".join(f"Group {i + 1}:\n" + "\n".join(compact_card(pj) for pj in g) for i, g in enumerate(groups)),
    )
    parsed, _ = call("deep", prompt, SplitNaming, method="json_schema")
    proposal["archetypes"].remove(target)
    existing = {a["key"] for a in proposal["archetypes"]}
    for g, d in zip(groups, parsed.parts):
        k = slugify(d.name)
        while k in existing:
            k += "-2"
        existing.add(k)
        proposal["archetypes"].append({
            "key": k, "name": d.name, "definition": d.definition, "include": d.include, "exclude": d.exclude,
            "defining_skills": d.defining_skills, "maps_from": target["maps_from"],
            "from_clusters": target.get("from_clusters", []), "from_taxonomy": target.get("from_taxonomy", []),
            "members": sorted(pj.job_id for pj in g),
        })
