"""Cover letters (pipeline revamp, Phase 5): one per job, grounded in the CV
sent with it and the project database. Draft (Sonnet) -> critique (Sonnet),
up to MAX_ROUNDS, with deterministic checks like the CV loop's."""
import json
import re

from sqlmodel import Session, select

from src.cv import library
from src.db import CoverLetter, Job
from src.lanes.core import lane_by_key
from src.profile import context as pc
from src.llm.call import call, load_prompt, truncate
from src.llm.config import model_label
from src.llm.schemas import CoverLetterCritique, CoverLetterDraft

MAX_ROUNDS = 2
MIN_WORDS, MAX_WORDS = 180, 380
MANUAL_EDIT = "manual-edit"


def _norm(t: str) -> str:
    return re.sub(r"[\s*_`]+", " ", t).strip().lower()


def cv_for_letter(session: Session, job: Job) -> tuple[str, str] | None:
    """(markdown, ref): the CV this job sends (its edited copy, else the library CV with the lane line)."""
    return library.effective_cv(session, job)


HYPE = ("thrilled", "passionate", "excited to", "i'd welcome", "leverage", "at scale", "maps directly",
        "aligns with", "align with", "world-class", "cutting-edge")


def _checks(body: str, company: str, facts: str = "") -> list[str]:
    problems = []
    words = len(body.split())
    if words > MAX_WORDS:
        problems.append(f"The letter is {words} words; cut it to at most {MAX_WORDS - 30}.")
    if words < MIN_WORDS:
        problems.append(f"The letter is only {words} words; develop the evidence paragraphs (aim for 220-350).")
    if re.search(r"\b[Gg]rade[sd]?\s*(?:of\s*)?\d|\bGPA\b|\d(?:\.\d+)?\s*/\s*6(?:\.0+)?\b", body):  # "grade 5.5", "GPA", "5.5/6"; not "within one grade"
        problems.append("Remove grades from the letter.")
    metrics = re.findall(r"\d[\d.,]*\s*(?:%|percent\b|million\b|billion\b|days\b|x\b)|\b\d+(?:\.\d+)?x\b", body)
    if len(metrics) > 1:
        problems.append(f"Too much detail for a cover letter ({', '.join(metrics[:4])}): describe the experience in general terms; the numbers belong in the CV.")
    for word in ("permit", "sponsorship"):
        if word in facts.lower() and word not in body.lower():
            problems.append(f"State the practical facts for HR in the closing paragraph (work {word}): {facts}")
            break
    if re.search(r"\s[\u2014\u2013]\s|\u2014", body):
        problems.append("Replace the em/en dashes with a period, comma or colon.")
    hype = [w for w in HYPE if w in body.lower()]
    if hype:
        problems.append(f"Drop the hype phrasing: {', '.join(hype)}. Say it plainly.")
    first = next((w for w in re.findall(r"[A-Za-z][A-Za-z&.-]+", company or "") if w.lower() not in {"the", "ag", "sa", "gmbh", "ltd", "inc"}), None)
    if first and first.lower() not in body.lower():
        problems.append(f"The letter never names the company ({company}).")
    return problems


def generate(session: Session, job: Job, seed: CoverLetter | None = None) -> CoverLetter:
    src = cv_for_letter(session, job)
    if src is None:
        raise ValueError("No CV for this job yet: generate its archetype CV in the CV library (or tailor one) first.")
    cv_md, cv_ref = src
    lane = lane_by_key(job.lane)
    projects = pc.load_projects_for_cv()
    body, feedback, tokens, rounds = (seed.body_markdown if seed else ""), (seed.feedback if seed else ""), 0, 0
    crit = None
    for rounds in range(1, MAX_ROUNDS + 1):
        previous = f"Draft:\n{body}\n\nFeedback:\n{feedback}" if body else "(none: first draft)"
        prompt = load_prompt("letters/draft").format(
            job_title=job.title, job_company=job.company, job_location=job.location or "-",
            lane_name=lane.name if lane else "unknown", lane_slot=lane.slot if lane else "",
            job_description=truncate(job.description, n=6000), cv=cv_md, projects=projects, previous=previous,
            motivation=pc.load_motivation(), letter_facts=(lane.letter if lane else "") or "(none)",
        )
        draft, log = call("deep", prompt, CoverLetterDraft, method="json_schema")
        tokens += log.input_tokens + log.output_tokens
        body = pc.strip_grades(draft.body_markdown.strip())
        prompt = load_prompt("letters/critique").format(
            job_title=job.title, job_company=job.company, job_description=truncate(job.description, n=6000),
            cv=cv_md, projects=projects, letter=body, motivation=pc.load_motivation(),
            letter_facts=(lane.letter if lane else "") or "(none)",
        )
        crit, log = call("deep", prompt, CoverLetterCritique, method="json_schema")
        tokens += log.input_tokens + log.output_tokens
        honesty = crit.honesty_score
        if honesty < 4 and not any(len(_norm(q)) >= 3 and _norm(q) in _norm(body) for q in crit.fabrication_quotes):
            honesty = 4  # same backstop as the CV critique: an accusation must quote the letter
        crit.honesty_score = honesty
        problems = _checks(body, job.company, lane.letter if lane else "")
        verdict = crit.verdict
        if problems or honesty < 5 or min(crit.relevance_score, crit.specificity_score, crit.tone_score) < 4:
            verdict = "revise"
        feedback = " ".join(problems + [crit.feedback])
        crit.verdict = verdict
        if verdict == "approve":
            break
    letter = CoverLetter(
        job_id=job.id, cv_ref=cv_ref, body_markdown=body, verdict=crit.verdict,
        honesty_score=crit.honesty_score, relevance_score=crit.relevance_score,
        specificity_score=crit.specificity_score, tone_score=crit.tone_score,
        feedback=feedback, attempt_count=rounds, model_used=model_label("deep"), tokens=tokens,
    )
    session.add(letter)
    session.commit()
    session.refresh(letter)
    return letter


def save_edit(session: Session, base: CoverLetter, body: str, header: str | None = None, subject: str | None = None) -> CoverLetter:
    """A hand edit becomes a new version. header/subject are stored only when they differ
    from the automatic ones (so an untouched header keeps today's date)."""
    letter = CoverLetter(job_id=base.job_id, cv_ref=base.cv_ref, body_markdown=body, header=header, subject=subject, verdict=base.verdict,
                         honesty_score=base.honesty_score, relevance_score=base.relevance_score,
                         specificity_score=base.specificity_score, tone_score=base.tone_score,
                         feedback=base.feedback, attempt_count=base.attempt_count, model_used=MANUAL_EDIT, tokens=0)
    session.add(letter)
    session.commit()
    session.refresh(letter)
    return letter


def letters_for(session: Session, job_id: str) -> list[CoverLetter]:
    return session.exec(select(CoverLetter).where(CoverLetter.job_id == job_id).order_by(CoverLetter.id)).all()


_SIGNOFF = re.compile(r"\n+\s*((?:Kind|Best|Warm) regards|Sincerely|Yours sincerely)[,.]?\s*(?:\n.*)?$", re.S | re.I)


def _contact(session=None) -> dict:
    """Name and contact details from the CV template header (never hard-coded)."""
    text = library.TEMPLATE.read_text() if library.TEMPLATE.exists() else ""
    field = lambda label: (re.search(rf"{label}:\s*([^·\n]+)", text) or [None, ""])[1].strip()  # noqa: E731
    name = (re.search(r"^# (.+)$", text, re.M) or [None, ""])[1].strip()
    address = field("Address")
    m = re.search(r"\d{4,5}\s+([^,]+),\s*(.+)$", address)  # "8055 Zürich, Switzerland" -> city, country
    city, country = (m.group(1).strip(), m.group(2).strip()) if m else ("", "")
    return {"name": name, "city": city, "country": country, "phone": field("Phone").replace("-", " "),
            "email": field("Email"), "website": field("Website")}


def _subject(session: Session, job: Job) -> str:
    """'Application: <role> (6 months, from 1 February 2027)' from the role card's timeline signals."""
    from src.db import RoleCard

    card = session.get(RoleCard, job.id)
    sig = json.loads(card.lane_signals or "{}") if card else {}
    bits = []
    if sig.get("duration_months"):
        bits.append(f"{sig['duration_months']} months")
    start = (sig.get("start_date") or "").strip()
    if start and start.lower() not in ("asap", "immediately", "by agreement", "none"):
        bits.append(("from " if start[:1].isdigit() else "starting ") + start)
    return f"Application: {job.title}" + (f" ({', '.join(bits)})" if bits else "")


def default_header(job: Job) -> str:
    """Place and date, then the recipient lines."""
    from datetime import date

    today = date.today()
    return "\n".join([f"{_contact()['city'] or 'Zürich'}, {today.day} {today.strftime('%B %Y')}", job.company or "", "Human Resources"])


def pdf_parts(session: Session, job: Job, letter: CoverLetter, body: str | None = None,
              header: str | None = None, subject: str | None = None) -> dict:
    """Everything the letter template needs: header lines (place/date, recipient), subject,
    body (greeting to last paragraph), sign-off and contact footer. body/header/subject
    override the saved letter (live preview while editing)."""
    c = _contact()
    body = (letter.body_markdown if body is None else body).strip()
    header = header if header is not None else (letter.header or default_header(job))
    subject = subject if subject is not None else (letter.subject or _subject(session, job))
    m = _SIGNOFF.search(body)
    signoff = (m.group(1) + ",") if m else "Kind regards,"
    if m:
        body = body[:m.start()].rstrip()
    return {
        "header": [ln.strip() for ln in header.replace("\r\n", "\n").split("\n")],
        "subject": subject.strip(),
        "body": body,
        "signoff": signoff,
        "name": c["name"],
        "contact": [" ".join(x for x in (", ".join(y for y in (c["city"], c["country"]) if y), c["phone"]) if x),
                    " ".join(x for x in (c["email"], c["website"]) if x)],
    }


def full_markdown(parts: dict) -> str:
    """The whole letter as Markdown for the job page preview: same parts as the PDF."""
    lines = lambda xs: "\n".join(x for x in xs if x)  # noqa: E731 (rendered with breaks: true)
    return "\n\n".join(x for x in [lines(parts["header"]), f"**{parts['subject']}**" if parts["subject"] else "",
                                    parts["body"], parts["signoff"], lines([parts["name"], *parts["contact"]])] if x)
