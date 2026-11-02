"""Application tracking: a dated stage log per job.

Stages fall in three groups:
- triage: before applying (shortlist, skipped). "new" is the absence of events.
- process: applied and everything after it. Needs an Applied event; any order.
- outcome: closes an application, remembering the furthest stage reached.

Lab outreach entries (Job.kind == "outreach") use the same log with their own names:
Sent, Replied, Meeting, Topic offered, Agreed / Declined / No topic / No reply. "New" reads
"To contact"; there is no Assessment, Shortlist or Position closed.

Tracking.status is a cache of the log (the latest event, an outcome always winning),
so the board's filters and sorts never have to read the events. Only `log_stage`,
`update_event` and `delete_event` change the log, and each re-syncs the cache.
"""
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlmodel import Session, select

from src.db import StageEvent, Tracking

FOLLOW_UP_DAYS = 14  # an open application with no news this long gets a "follow up?" flag


@dataclass(frozen=True)
class Stage:
    key: str
    label: str
    group: str  # triage | process | outcome
    rank: int = 0  # process order, for "furthest stage reached" and the board stepper
    repeatable: bool = False
    needs_offer: bool = False
    scheduled: bool = False  # has a time and a "how did it go?" debrief


STAGES = {s.key: s for s in [
    Stage("shortlist", "Shortlisted", "triage"),
    Stage("skipped", "Skipped", "triage"),
    Stage("applied", "Applied", "process", rank=1),
    Stage("screening", "Screening call", "process", rank=2, repeatable=True, scheduled=True),
    Stage("assessment", "Assessment", "process", rank=3, repeatable=True),
    Stage("interview", "Interview", "process", rank=4, repeatable=True, scheduled=True),
    Stage("offer", "Offer", "process", rank=5),
    Stage("rejected", "Rejected", "outcome"),
    Stage("no_response", "No response", "outcome"),
    Stage("withdrawn", "Withdrawn", "outcome"),
    Stage("closed", "Position closed", "outcome"),
    Stage("declined", "Offer declined", "outcome", needs_offer=True),
    Stage("accepted", "Offer accepted", "outcome", needs_offer=True),
]}
STATUS_LABELS = {"new": "New", **{k: s.label for k, s in STAGES.items()}}
STEPPER = ["applied", "screening", "interview", "offer"]  # the board's mini progress line

OUTREACH_LABELS = {
    "new": "To contact", "skipped": "Skipped", "applied": "Sent", "screening": "Replied", "interview": "Meeting",
    "offer": "Topic offered", "rejected": "No topic", "no_response": "No reply", "withdrawn": "Withdrawn",
    "declined": "Declined", "accepted": "Agreed",
}
OUTREACH_SCHEDULED = {"interview"}  # a reply is an email, a meeting has a time and a debrief


def labels_for(kind: str = "job") -> dict[str, str]:
    return OUTREACH_LABELS if kind == "outreach" else STATUS_LABELS


def label(stage: str, kind: str = "job") -> str:
    return labels_for(kind).get(stage, stage)


def is_scheduled(stage: str, kind: str = "job") -> bool:
    if kind == "outreach":
        return stage in OUTREACH_SCHEDULED
    return STAGES[stage].scheduled if stage in STAGES else False

INTERVIEW_KINDS = ["Recruiter screen", "Technical", "Case study", "Behavioural / hiring manager", "Final / onsite"]
FORMATS = ["Video", "Phone", "Onsite"]


class StageError(ValueError):
    """A log entry that breaks the rules; the message is shown to me as is."""


class NeedsReopen(StageError):
    """The application is closed; logging this stage would reopen it."""


def today() -> str:
    return date.today().isoformat()


def group_of(status: str) -> str:
    return STAGES[status].group if status in STAGES else "triage"


def detail_of(ev: StageEvent) -> dict:
    try:
        return json.loads(ev.detail or "{}")
    except json.JSONDecodeError:
        return {}


def _order(e: StageEvent):
    """By date, then time, then logging order (ids grow as entries are logged)."""
    return (e.date, e.time or "", e.id or 0)


def events_for(session: Session, job_id: str) -> list[StageEvent]:
    """The job's log in order: by date, then by when I logged it."""
    rows = session.exec(select(StageEvent).where(StageEvent.job_id == job_id)).all()
    return sorted(rows, key=_order)


def all_events(session: Session) -> dict[str, list[StageEvent]]:
    out: dict[str, list[StageEvent]] = {}
    for e in sorted(session.exec(select(StageEvent)).all(), key=_order):
        out.setdefault(e.job_id, []).append(e)
    return out


def derive_status(events: list[StageEvent]) -> str:
    if not events:
        return "new"
    outcome = next((e for e in reversed(events) if group_of(e.stage) == "outcome"), None)
    return outcome.stage if outcome else events[-1].stage


def ensure_tracking(session: Session, job_id: str) -> Tracking:
    tr = session.exec(select(Tracking).where(Tracking.job_id == job_id)).first()
    if tr is None:
        tr = Tracking(job_id=job_id, status="new")
        session.add(tr)
        session.flush()
    return tr


def sync(session: Session, job_id: str) -> Tracking:
    """Re-derive the cached status and applied date from the log."""
    session.flush()
    events = events_for(session, job_id)
    tr = ensure_tracking(session, job_id)
    tr.status = derive_status(events)
    applied = next((e for e in events if e.stage == "applied"), None)
    tr.applied_at = datetime.fromisoformat(applied.date) if applied else None
    tr.updated_at = datetime.now(timezone.utc)
    session.add(tr)
    return tr


def _clean_date(value: str | None, label: str = "Date") -> str:
    value = (value or "").strip() or today()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise StageError(f"{label} must be a date (YYYY-MM-DD).")


def _clean_detail(stage: str, detail: dict | None, events: list[StageEvent]) -> dict:
    detail = {k: v for k, v in (detail or {}).items() if v not in (None, "", [])}
    if stage == "interview" and not detail.get("round"):
        detail["round"] = sum(1 for e in events if e.stage == "interview") + 1
    return detail


def log_stage(session: Session, job_id: str, stage: str, *, on: str | None = None, time: str | None = None,
              detail: dict | None = None, note: str | None = None, applied_on: str | None = None,
              reopen: bool = False, snapshot=None, kind: str = "job") -> StageEvent:
    """Add one event, enforcing the rules. Caller commits.

    - triage stages only before applying ("new" = delete the triage events, see reset_triage)
    - process and outcome stages need an Applied event; if there is none, one is added
      dated `applied_on` (default: the same date)
    - one Applied and one Offer per application; offer outcomes need an Offer
    - a closed application only takes new entries with reopen=True, which drops the outcome
    `snapshot(session, job_id)` records what I sent when the Applied event is created.
    """
    if stage not in STAGES or stage not in labels_for(kind):
        raise StageError(f"Unknown stage: {stage}")
    st = STAGES[stage]
    name = label(stage, kind)
    on = _clean_date(on)
    events = events_for(session, job_id)
    has = {e.stage for e in events}
    applied = "applied" in has
    outcome = next((e for e in events if group_of(e.stage) == "outcome"), None)

    if st.group == "triage":
        if applied:
            raise StageError(f"Already {label('applied', kind).lower()}: use Withdrawn instead of skipping, or delete the {label('applied', kind)} entry.")
        for e in events:  # triage is a single choice: replace the previous one
            session.delete(e)
    else:
        if outcome and not reopen:
            raise NeedsReopen(f"This is closed ({label(outcome.stage, kind)}). Reopen it to log this?")
        if outcome:
            session.delete(outcome)
        if stage in ("applied", "offer") and stage in has:
            raise StageError(f"There is already a {name} entry: edit that one instead.")
        if st.needs_offer and "offer" not in has:
            raise StageError(f"Log the {label('offer', kind)} first.")
        if not applied and stage != "applied":
            applied_on = _clean_date(applied_on or on, "Applied date")
            if applied_on > on:
                raise StageError(f"The {label('applied', kind).lower()} date can't be after this entry's date.")
            _add(session, job_id, "applied", applied_on, snapshot=snapshot)
        for e in events:  # applying ends triage
            if group_of(e.stage) == "triage":
                session.delete(e)

    ev = StageEvent(job_id=job_id, stage=stage, date=on, time=(time or None),
                    detail=json.dumps(_clean_detail(stage, detail, events)), note=(note or None))
    session.add(ev)
    if stage == "applied" and snapshot:
        snapshot(session, job_id)
    sync(session, job_id)
    return ev


def _add(session: Session, job_id: str, stage: str, on: str, snapshot=None) -> StageEvent:
    ev = StageEvent(job_id=job_id, stage=stage, date=on)
    session.add(ev)
    if stage == "applied" and snapshot:
        snapshot(session, job_id)
    return ev


def update_event(session: Session, ev: StageEvent, *, on: str | None = None, time: str | None = None,
                 detail: dict | None = None, note: str | None = None, debrief: str | None = None,
                 questions: str | None = None) -> StageEvent:
    """Edit an entry's date and notes (its stage stays; delete and re-log to change it). Caller commits."""
    ev.date = _clean_date(on or ev.date)
    ev.time = time or None
    ev.detail = json.dumps({k: v for k, v in (detail or {}).items() if v not in (None, "", [])})
    ev.note, ev.debrief, ev.questions = note or None, debrief or None, questions or None
    ev.estimated = False
    session.add(ev)
    sync(session, ev.job_id)
    return ev


def delete_event(session: Session, ev: StageEvent) -> None:
    """Remove an entry. Deleting Applied removes the whole application (it can't exist without it)."""
    job_id = ev.job_id
    if ev.stage == "applied":
        for e in events_for(session, job_id):
            if group_of(e.stage) != "triage":
                session.delete(e)
    else:
        session.delete(ev)
    sync(session, job_id)


def reset_triage(session: Session, job_id: str) -> None:
    """Back to "needs review": only before applying."""
    events = events_for(session, job_id)
    if any(e.stage == "applied" for e in events):
        raise StageError("Already applied: delete the Applied entry first.")
    for e in events:
        session.delete(e)
    sync(session, job_id)


# --- reading the log -------------------------------------------------------

def event_label(ev: StageEvent, kind: str = "job") -> str:
    d = detail_of(ev)
    name = label(ev.stage, kind)
    if ev.stage == "interview" and d.get("round"):
        name = f"{name} {d['round']}"
    return name


def event_dict(ev: StageEvent, kind: str = "job") -> dict:
    return {
        "id": ev.id, "stage": ev.stage, "label": event_label(ev, kind), "group": group_of(ev.stage),
        "date": ev.date, "time": ev.time, "detail": detail_of(ev), "note": ev.note or "",
        "debrief": ev.debrief or "", "questions": ev.questions or "", "estimated": ev.estimated,
        "upcoming": ev.date > today(),
        "needs_debrief": is_scheduled(ev.stage, kind) and ev.date <= today()
                         and not (ev.debrief or ev.questions or detail_of(ev).get("rating")),
    }


def furthest(events: list[StageEvent]) -> StageEvent | None:
    """The furthest process stage reached (latest one of that rank)."""
    process = [e for e in events if group_of(e.stage) == "process"]
    return max(process, key=lambda e: (STAGES[e.stage].rank, *_order(e))) if process else None


def _days_since(iso: str) -> int:
    return (date.today() - date.fromisoformat(iso)).days


def next_action(events: list[StageEvent], kind: str = "job") -> dict | None:
    """What needs doing for an open application, most urgent first."""
    status = derive_status(events)
    if group_of(status) != "process":
        return None
    upcoming = [e for e in events if e.date > today()]
    if upcoming:
        e = upcoming[0]
        return {"kind": "upcoming", "label": event_label(e, kind), "date": e.date, "time": e.time}
    for e in reversed(events):
        if e.stage == "assessment":
            d = detail_of(e)
            if d.get("due") and not d.get("submitted"):
                return {"kind": "due", "label": "Assessment due", "date": d["due"]}
    pending = [e for e in events if event_dict(e, kind)["needs_debrief"]]
    if pending:
        e = pending[-1]
        return {"kind": "debrief", "label": f"How did {event_label(e, kind)} go?", "date": e.date, "event_id": e.id}
    last = events[-1]
    if _days_since(last.date) >= FOLLOW_UP_DAYS and status in ("applied", "assessment", "screening", "interview"):
        return {"kind": "follow_up", "label": "Follow up?", "date": last.date, "days": _days_since(last.date)}
    return None


def summary(events: list[StageEvent], kind: str = "job") -> dict:
    """Everything the board needs about one job's application (or lab outreach), as plain data."""
    status = derive_status(events)
    applied = next((e for e in events if e.stage == "applied"), None)
    top = furthest(events)
    outcome = next((e for e in reversed(events) if group_of(e.stage) == "outcome"), None)
    past = [e for e in events if e.date <= today()]
    last = past[-1] if past else (events[-1] if events else None)
    current = outcome or (events[-1] if events else None)
    reached = STAGES[top.stage].rank if top else 0
    return {
        "kind": kind,
        "status": status,
        "status_label": label(status, kind),
        "group": group_of(status),
        "applied": bool(applied),
        "closed": bool(outcome),
        "stage_label": (f"{label(outcome.stage, kind)} after {event_label(top, kind)}"
                        if outcome and top and top.stage not in ("applied", "offer") else
                        event_label(current, kind) if current else label("new", kind)),
        "stage_date": current.date if current else None,
        "stage_estimated": bool(current and current.estimated),
        "applied_date": applied.date if applied else None,
        "applied_estimated": bool(applied and applied.estimated),
        "last_activity": last.date if last else None,
        "reached": reached,
        # done: it happened; passed: skipped on the way to a later stage
        "stepper": [{"stage": s, "label": label(s, kind), "done": any(e.stage == s for e in events),
                     "passed": STAGES[s].rank <= reached,
                     "date": next((e.date for e in events if e.stage == s), None)} for s in STEPPER],
        "next": next_action(events, kind),
        "events": [event_dict(e, kind) for e in events],
    }


def first_response_days(events: list[StageEvent]) -> int | None:
    """Days from Applied to the first thing that happened after it (any stage or outcome but No response)."""
    applied = next((e for e in events if e.stage == "applied"), None)
    if not applied:
        return None
    after = [e for e in events if e is not applied and e.stage not in ("no_response",) and group_of(e.stage) != "triage"]
    if not after:
        return None
    return (date.fromisoformat(after[0].date) - date.fromisoformat(applied.date)).days


def upcoming_events(session: Session) -> list[StageEvent]:
    return sorted((e for e in session.exec(select(StageEvent).where(StageEvent.date >= today())).all()),
                  key=lambda e: (e.date, e.time or ""))


def ics(events: list[tuple[StageEvent, str]]) -> str:
    """A calendar file for scheduled events. `events` pairs each event with its title."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//job-radar//EN", "CALSCALE:GREGORIAN"]
    for ev, title in events:
        day = ev.date.replace("-", "")
        lines += ["BEGIN:VEVENT", f"UID:job-radar-{ev.id}@localhost", f"DTSTAMP:{stamp}"]
        if ev.time:
            start = datetime.fromisoformat(f"{ev.date}T{ev.time}")
            end = start + timedelta(hours=1)
            lines += [f"DTSTART;TZID=Europe/Zurich:{start:%Y%m%dT%H%M%S}", f"DTEND;TZID=Europe/Zurich:{end:%Y%m%dT%H%M%S}"]
        else:
            nxt = (date.fromisoformat(ev.date) + timedelta(days=1)).isoformat().replace("-", "")
            lines += [f"DTSTART;VALUE=DATE:{day}", f"DTEND;VALUE=DATE:{nxt}"]
        summary_text = title.replace(",", "\\,").replace(";", "\\;")
        lines += [f"SUMMARY:{summary_text}"]
        if ev.note:
            lines.append("DESCRIPTION:" + ev.note.replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;"))
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
