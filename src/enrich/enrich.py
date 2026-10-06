"""enrich_job(): role card extraction, skill canonicalization, embedding.

Each step is skipped when its output is already current:
- role card: re-extracted only if missing, on an older ROLE_CARD_PROMPT_VERSION, or force=True
- embedding: recomputed only if the card text or the embedding model changed
"""
import json
import re

from sqlmodel import Session, select

from src.db import Embedding, Job, JobSkill, RoleCard
from src.enrich.embeddings import EMBED_MODEL, embed_texts, text_hash, to_bytes
from src.enrich.skills import job_skill_names, known_skills_prompt, resolve_skill
from src.llm.call import call, load_prompt, truncate
from src.llm.config import model_label
from src.llm.schemas import RoleCardExtraction

ROLE_CARD_PROMPT_VERSION = "v1"
ROLE_CARD_ROLE = "deep"  # Sonnet: cards feed every comparison, so quality matters more than the extra cent

# A card should be English; German function words in it mean the instruction slipped.
_GERMAN_WORDS = {"und", "der", "die", "das", "mit", "für", "wir", "sie", "ist", "von", "zu", "im", "auf", "eine", "ein", "oder", "bei", "des"}


def _reads_as_english(text: str) -> bool:
    words = re.findall(r"[a-zäöüß]+", text.lower())
    if len(words) < 8:
        return True
    return sum(w in _GERMAN_WORDS for w in words) / len(words) < 0.04


def card_text(card: RoleCard, skills: dict[str, list[str]]) -> str:
    """The text that gets embedded: role only, fixed field order."""
    parts = [
        card.title_normalized,
        card.summary,
        "Responsibilities: " + "; ".join(json.loads(card.responsibilities or "[]")),
        "Required skills: " + ", ".join(skills.get("required", [])),
    ]
    if skills.get("nice_to_have"):
        parts.append("Nice to have: " + ", ".join(skills["nice_to_have"]))
    if card.domain:
        parts.append("Domain: " + card.domain)
    parts.append("Level: " + card.level)
    return "\n".join(parts)


def extract_role_card(session: Session, job: Job) -> RoleCard:
    prompt = load_prompt("enrich/role_card").format(
        known_skills=known_skills_prompt(session),
        job_title=job.title or "(untitled)",
        job_company=job.company or "(unknown)",
        job_location=job.location or "(not specified)",
        job_description=truncate(job.description, n=8000),
    )
    # Native structured outputs: on long postings, tool calling sometimes returned
    # the skills list as text (2 of 140 in the first backfill).
    try:
        parsed, _log = call(ROLE_CARD_ROLE, prompt, RoleCardExtraction, method="json_schema")
    except ValueError:  # one retry for the rare remaining miss
        parsed, _log = call(ROLE_CARD_ROLE, prompt, RoleCardExtraction, method="json_schema")

    card = session.get(RoleCard, job.id) or RoleCard(job_id=job.id, prompt_version="", model="", title_normalized="", summary="")
    card.prompt_version = ROLE_CARD_PROMPT_VERSION
    card.model = model_label(ROLE_CARD_ROLE)
    card.title_normalized = parsed.title_normalized
    card.summary = parsed.summary
    card.responsibilities = json.dumps(parsed.responsibilities)
    card.domain = parsed.domain
    card.level = parsed.level
    card.languages_required = json.dumps(parsed.languages_required)
    card.lane_signals = parsed.lane_signals.model_dump_json()
    card.information_quality = parsed.information_quality
    card.language_ok = _reads_as_english(" ".join([parsed.summary, *parsed.responsibilities]))
    session.add(card)
    if not (job.title or "").strip():  # e.g. a manual add whose fetch found no title
        job.title = parsed.title_normalized
        session.add(job)

    for link in session.exec(select(JobSkill).where(JobSkill.job_id == job.id)).all():
        session.delete(link)
    session.flush()
    seen: dict[int, JobSkill] = {}
    for sk in parsed.skills:
        skill = resolve_skill(session, sk.name, sk.category)
        if skill.id in seen:  # two raw terms mapped to one skill: keep the stronger importance
            if sk.importance == "required":
                seen[skill.id].importance = "required"
            continue
        link = JobSkill(job_id=job.id, skill_id=skill.id, importance=sk.importance, raw_term=sk.raw_term)
        seen[skill.id] = link
        session.add(link)
    session.flush()
    return card


def ensure_embedding(session: Session, card: RoleCard) -> bool:
    """Returns True if a vector was (re)computed."""
    text = card_text(card, job_skill_names(session, card.job_id))
    h = text_hash(text)
    emb = session.get(Embedding, card.job_id)
    if emb and emb.role_card_hash == h and emb.model == EMBED_MODEL:
        return False
    vec = embed_texts([text])[0]
    emb = emb or Embedding(job_id=card.job_id, model=EMBED_MODEL, role_card_hash=h, dim=len(vec), vector=b"")
    emb.model, emb.role_card_hash, emb.dim, emb.vector = EMBED_MODEL, h, len(vec), to_bytes(vec)
    session.add(emb)
    session.flush()
    return True


def enrich_job(session: Session, job: Job, force: bool = False) -> dict:
    """Bring one job's role card, skills and embedding up to date. Caller commits."""
    card = session.get(RoleCard, job.id)
    extracted = False
    if force or card is None or card.prompt_version != ROLE_CARD_PROMPT_VERSION:
        if not (job.description or "").strip():
            return {"job_id": job.id, "skipped": "no description"}
        card = extract_role_card(session, job)
        extracted = True
    embedded = ensure_embedding(session, card)
    return {"job_id": job.id, "extracted": extracted, "embedded": embedded, "language_ok": card.language_ok, "quality": card.information_quality}
