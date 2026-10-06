"""Lanes (pipeline revamp, Phase 5): why and when a job is applied to.

- load_lanes():   parse profile/lanes.md (Key, Detect, Eligible, Value, CV slot)
- detect():       deterministic lane from role-card signals, None when ambiguous
- assess_job():   Sonnet checks eligibility + lane value (+ deadline); resolves ambiguous lanes
- fit(), urgency(), priority(): ranking = fit x lane value x urgency (docs §5.7)
"""
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlmodel import Session

from src.db import Job, JobSkill, LaneAssessment, RoleCard
from src.profile import context as pc
from src.llm.call import call, load_prompt, truncate
from src.llm.config import model_label
from src.llm.schemas import LaneJudgment


@dataclass
class Lane:
    key: str
    name: str
    detect: str
    eligible: str
    value: str
    slot: str
    letter: str = ""


def lanes_text() -> str:
    path = pc.PROFILE_DIR / "lanes.md"
    return path.read_text() if path.exists() else ""


def load_lanes() -> list[Lane]:
    out = []
    for block in re.split(r"^## ", lanes_text(), flags=re.M)[1:]:
        name, _, body = block.partition("\n")
        f = {k.lower(): v.strip() for k, v in re.findall(r"^- \*\*([^*]+):\*\*\s*(.*)$", body, re.M)}
        if f.get("key"):
            out.append(Lane(f["key"], name.strip(), f.get("detect", ""), f.get("eligible", ""), f.get("value", ""), f.get("cv slot", ""), f.get("letter facts", "")))
    return out


def lanes_hash() -> str:
    return hashlib.sha1(lanes_text().encode()).hexdigest()


def lane_by_key(key: str | None) -> Lane | None:
    return next((l for l in load_lanes() if l.key == key), None)


_MONTHS_SUMMER = ("may", "june", "july", "august", "summer", "mai", "juni", "juli", "sommer")


def _timeline(card: RoleCard, title: str, description: str | None) -> dict:
    """Timeline facts from the role card plus the posting text (weeks, 'Summer 2027', start month)."""
    sig = json.loads(card.lane_signals or "{}")
    text = f"{title} {description or ''}".lower()
    weeks = [int(w) for w in re.findall(r"(\d{1,2})\s*(?:-|to)?\s*(?:\d{1,2}\s*)?(?:weeks|wochen)", text)]
    months = sig.get("duration_months") or (round(max(weeks) / 4.3) if weeks else None)
    start = (sig.get("start_date") or "").lower()
    summer = bool(re.search(r"\bsummer\s*(?:20\d\d)?\b|\bsommer\b", text)) or any(m in start for m in _MONTHS_SUMMER)
    return {"type": sig.get("employment_type"), "months": months, "summer": summer, "thesis": bool(sig.get("mentions_thesis")),
            "part_time": (sig.get("workload_max_pct") or 100) <= 60}


def detect(card: RoleCard, title: str, description: str | None = None) -> str | None:
    """Clear cases only; None means 'let the LLM decide'. Keys follow lanes.md.
    Timeline first: a fixed-length full-time internship is never a working-student job."""
    keys = {l.key for l in load_lanes()}
    t = _timeline(card, title, description)
    pick = None
    if t["thesis"] or t["type"] == "thesis":
        pick = "thesis-internship"
    elif t["type"] == "internship" or (t["months"] and t["months"] <= 6 and not t["part_time"] and "intern" in (title or "").lower()):
        if t["summer"] or (t["months"] is not None and t["months"] <= 4):
            pick = "summer-internship"
        elif t["months"] is not None and 5 <= t["months"] <= 8:
            pick = "thesis-internship"  # a regular ~6-month internship: the internship + master's thesis lane
    elif t["type"] in ("working_student", "part_time"):
        pick = "working-student"
    elif t["type"] in ("full_time", "contract"):
        pick = "full-time"
    return pick if pick in keys else None


def _guard_lane(lane: str, card: RoleCard, title: str, description: str | None) -> str:
    """Overrule an LLM lane that contradicts the timeline (e.g. 'working student' for a 13-week full-time internship)."""
    t = _timeline(card, title, description)
    internship = t["type"] in ("internship", "thesis") or "intern" in (title or "").lower()
    if lane == "working-student" and internship and not t["part_time"] and (t["months"] or 99) <= 6:
        return "summer-internship" if t["summer"] or (t["months"] or 99) <= 4 else "thesis-internship"
    return lane


def _lanes_prompt(lanes: list[Lane]) -> str:
    return "\n\n".join(f"### {l.key}: {l.name}\nDetect: {l.detect}\nEligible: {l.eligible}\nValue: {l.value}" for l in lanes)


def assess_job(session: Session, job: Job) -> LaneAssessment | None:
    """Lane (unless you set it), eligibility, lane value and deadline. Caller commits."""
    card = session.get(RoleCard, job.id)
    lanes = load_lanes()
    if card is None or not lanes:
        return None
    fixed = job.lane if job.lane_source == "user" else detect(card, job.title, job.description)
    from src.archetypes.features import compact_card, load_jobs

    pj = load_jobs(session, [job.id])
    instruction = (f"The job's lane is **{fixed}** (already decided)." if fixed
                   else "First decide which lane the job belongs to (by its Detect signals and the timing it states).")
    prompt = load_prompt("lanes/assess").format(
        lanes=_lanes_prompt(lanes), card=compact_card(pj[0], max_summary=600) if pj else card.summary,
        description=truncate(job.description, n=5000), lane_instruction=instruction,
    )
    parsed, _ = call("deep", prompt, LaneJudgment, method="json_schema")
    lane = fixed or (parsed.lane if parsed.lane in {l.key for l in lanes} else None) or "full-time"
    if not fixed:
        lane = _guard_lane(lane, card, job.title, job.description)
    if job.lane_source != "user":
        job.lane, job.lane_source = lane, "auto"
    if parsed.deadline and not job.deadline and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parsed.deadline):
        job.deadline = parsed.deadline
    session.add(job)
    a = session.get(LaneAssessment, job.id) or LaneAssessment(job_id=job.id, lane=lane)
    a.lane, a.eligible = lane, parsed.eligible
    a.eligibility_reasons, a.value_reasons = json.dumps(parsed.eligibility_reasons), json.dumps(parsed.value_reasons)
    a.value_score = max(0.0, min(1.0, parsed.value_score))
    a.lanes_hash, a.model, a.created_at = lanes_hash(), model_label("deep"), datetime.now(timezone.utc)
    session.add(a)
    session.flush()
    return a


def fit(session: Session, job_id: str, evidenced: set[int]) -> dict:
    """Share of the job's skills your profile proves (required count fully, nice-to-have half)."""
    from sqlmodel import select

    from src.db import Skill

    rows = session.exec(select(JobSkill, Skill).where(JobSkill.job_id == job_id, JobSkill.skill_id == Skill.id)).all()
    if not rows:
        return {"score": None, "matched": [], "missing": []}
    total = got = 0.0
    matched, missing = [], []
    for link, sk in rows:
        w = 1.0 if link.importance == "required" else 0.5
        total += w
        if sk.id in evidenced:
            got += w
            matched.append(sk.name)
        elif link.importance == "required":
            missing.append(sk.name)
    return {"score": round(got / total, 2) if total else None, "matched": sorted(matched), "missing": sorted(missing)}


def urgency(job: Job) -> tuple[float, str]:
    today = date.today()
    if job.deadline:
        try:
            days = (date.fromisoformat(job.deadline) - today).days
        except ValueError:
            days = None
        if days is not None:
            if days < 0:
                return 0.2, f"deadline passed ({job.deadline})"
            if days <= 7:
                return 1.0, f"deadline in {days} day{'s' if days != 1 else ''}"
            if days <= 14:
                return 0.85, f"deadline in {days} days"
            if days <= 30:
                return 0.7, f"deadline in {days} days"
            return 0.5, f"deadline {job.deadline}"
    seen = job.posted_at or job.first_seen
    seen = seen if seen.tzinfo else seen.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - seen).days
    if age <= 7:
        return 0.7, f"no deadline · posted/added {age}d ago"
    if age <= 30:
        return 0.55, f"no deadline · {age}d old"
    return 0.4, f"no deadline · {age}d old"


def priority(fit_score: float | None, assessment: LaneAssessment | None, urg: float) -> float:
    f = fit_score if fit_score is not None else 0.5
    value = assessment.value_score if assessment else 0.5
    p = f * (0.3 + 0.7 * value) * urg
    if assessment and assessment.eligible == "no":
        p *= 0.3
    return round(p, 3)
