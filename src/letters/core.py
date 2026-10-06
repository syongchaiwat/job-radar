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


def save_edit(session: Session, base: CoverLetter, body: str) -> CoverLetter:
    letter = CoverLetter(job_id=base.job_id, cv_ref=base.cv_ref, body_markdown=body, verdict=base.verdict,
                         honesty_score=base.honesty_score, relevance_score=base.relevance_score,
                         specificity_score=base.specificity_score, tone_score=base.tone_score,
                         feedback=base.feedback, attempt_count=base.attempt_count, model_used=MANUAL_EDIT, tokens=0)
    session.add(letter)
    session.commit()
    session.refresh(letter)
    return letter


def letters_for(session: Session, job_id: str) -> list[CoverLetter]:
    return session.exec(select(CoverLetter).where(CoverLetter.job_id == job_id).order_by(CoverLetter.id)).all()


def pdf_parts(job: Job, letter: CoverLetter) -> tuple[str, list[str], str]:
    """(CV header markdown, date/recipient lines, body) for cv_pdf.letter_to_pdf."""
    from datetime import date

    header = ""
    if library.TEMPLATE.exists():
        text = re.sub(r"^---.*?---\s*", "", library.TEMPLATE.read_text(), flags=re.S)
        m = re.search(r"^# .+?(?=\n<!--|\n## )", text, re.S | re.M)
        header = m.group(0).strip() if m else ""
    meta = [date.today().strftime("%d %B %Y"), f"**{job.company}**" + (f", {job.location}" if job.location else ""), f"Re: {job.title}"]
    return header, meta, letter.body_markdown
