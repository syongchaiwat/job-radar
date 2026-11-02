"""Application analytics from the stage log: funnel, response rate, time to first response,
and the same numbers broken down by lane, archetype, source and which CV I sent.
Lab outreach entries are kept out of these and get their own small summary (outreach_stats)."""
from statistics import median

from sqlmodel import Session, select

from src.db import Job, Tracking
from src.tracking import core

FUNNEL = [("applied", "Applied", 1), ("screening", "Screening call", 2), ("assessment", "Assessment", 3),
          ("interview", "Interview", 4), ("offer", "Offer", 5)]


def _responded(events) -> bool:
    """Heard back: any entry after Applied other than my own No response / Withdrawn."""
    return any(e.stage not in ("applied", "no_response", "withdrawn") and core.group_of(e.stage) != "triage" for e in events)


def _row(apps: list[dict]) -> dict:
    n = len(apps)
    responded = sum(a["responded"] for a in apps)
    return {
        "n": n,
        "responded": responded,
        "response_rate": responded / n if n else 0,
        "interviewed": sum(a["reached"] >= 4 for a in apps),
        "offers": sum(a["reached"] >= 5 for a in apps),
        "open": sum(not a["closed"] for a in apps),
    }


def application_stats(session: Session, archetype_of: dict[str, str] | None = None) -> dict:
    """archetype_of maps job id -> archetype name (from the dashboard's active set)."""
    events = core.all_events(session)
    jobs = {j.id: j for j in session.exec(select(Job).where(Job.kind == "job")).all()}
    trackings = {t.job_id: t for t in session.exec(select(Tracking)).all()}
    apps = []
    for job_id, evs in events.items():
        if not any(e.stage == "applied" for e in evs) or job_id not in jobs:
            continue
        top = core.furthest(evs)
        tr = trackings.get(job_id)
        ref = tr.sent_cv_ref if tr else None
        apps.append({
            "job_id": job_id,
            "reached": core.STAGES[top.stage].rank if top else 1,
            "responded": _responded(evs),
            "closed": core.group_of(core.derive_status(evs)) == "outcome",
            "first_response": core.first_response_days(evs),
            "lane": jobs[job_id].lane or "none",
            "source": jobs[job_id].source or "unknown",
            "archetype": (archetype_of or {}).get(job_id) or "No archetype",
            "cv": "Edited for the job" if ref and ref.startswith("job:") else "Library CV" if ref else "Not recorded",
            "estimated": any(e.estimated for e in evs),
        })

    n = len(apps)
    funnel = [{"stage": key, "label": label, "n": sum(a["reached"] >= rank for a in apps),
               "share": (sum(a["reached"] >= rank for a in apps) / n) if n else 0} for key, label, rank in FUNNEL]
    waits = [a["first_response"] for a in apps if a["first_response"] is not None]

    def breakdown(field):
        groups: dict[str, list] = {}
        for a in apps:
            groups.setdefault(a[field], []).append(a)
        return sorted(({"key": k, **_row(v)} for k, v in groups.items()), key=lambda r: -r["n"])

    outcomes: dict[str, int] = {}
    for job_id, evs in events.items():
        if job_id not in jobs:
            continue
        st = core.derive_status(evs)
        if core.group_of(st) == "outcome":
            outcomes[st] = outcomes.get(st, 0) + 1

    return {
        "n": n,
        **_row(apps),
        "funnel": funnel,
        "median_first_response": median(waits) if waits else None,
        "n_first_response": len(waits),
        "outcomes": [{"stage": k, "label": core.STATUS_LABELS[k], "n": v} for k, v in sorted(outcomes.items(), key=lambda kv: -kv[1])],
        "by": {"lane": breakdown("lane"), "archetype": breakdown("archetype"), "source": breakdown("source"), "cv": breakdown("cv")},
        "n_estimated": sum(a["estimated"] for a in apps),
    }


def outreach_stats(session: Session) -> dict:
    """Lab outreach: to contact, sent, replied, meetings, topics offered, days to reply."""
    labs = [j.id for j in session.exec(select(Job).where(Job.kind == "outreach")).all()]
    events = core.all_events(session)
    sent = [events[j] for j in labs if any(e.stage == "applied" for e in events.get(j, []))]
    rank = lambda evs: core.STAGES[core.furthest(evs).stage].rank  # noqa: E731
    waits = [d for d in (core.first_response_days(evs) for evs in sent) if d is not None]
    return {
        "n": len(labs),
        "to_contact": sum(1 for j in labs if not events.get(j)),
        "sent": len(sent),
        "replied": sum(1 for evs in sent if _responded(evs)),
        "meetings": sum(1 for evs in sent if rank(evs) >= 4),
        "topics": sum(1 for evs in sent if rank(evs) >= 5),
        "agreed": sum(1 for evs in sent if core.derive_status(evs) == "accepted"),
        "median_days_to_reply": median(waits) if waits else None,
    }


def question_bank(session: Session) -> list[dict]:
    """Every interview / screening question I logged, newest first, with where it was asked."""
    jobs = {j.id: j for j in session.exec(select(Job)).all()}
    out = []
    for job_id, evs in core.all_events(session).items():
        for e in evs:
            if not e.questions:
                continue
            job = jobs.get(job_id)
            d = core.detail_of(e)
            for q in (line.strip(" -•\t") for line in e.questions.splitlines()):
                if q:
                    out.append({"question": q, "job_id": job_id, "company": job.company if job else "",
                                "title": job.title if job else "", "stage": core.event_label(e, job.kind if job else "job"),
                                "kind": d.get("kind", ""), "date": e.date})
    return sorted(out, key=lambda q: q["date"], reverse=True)
