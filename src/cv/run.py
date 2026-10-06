"""CLI: python -m src.cv.run --job-id <id> [--regenerate]

Runs the CV draft/critique graph for one job and writes the result to the DB
plus a Markdown export in cv_drafts/. generate_cv() is also called directly
by app/routes/job_detail.py -- this file is the one place that logic lives.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from src.db import CVDraft, Job, get_engine, init_db  # noqa: E402
from src.cv.export import export_cv_draft  # noqa: E402
from src.cv.graph import MAX_ATTEMPTS, build_cv_graph  # noqa: E402
from src.profile.context import strip_grades  # noqa: E402
from src.llm.schemas import CVDraftState  # noqa: E402

GRAPH = build_cv_graph()


_TEMPLATE_METADATA = re.compile(r"\s*·\s*source:\s*[^\s*]+|<!--.*?-->", re.DOTALL)


def _strip_template_metadata(markdown: str) -> str:
    """Template source tags and HTML comments are prompt-side metadata; the
    model occasionally copies them through, so strip deterministically. Same
    for course grades: already removed from the prompt sources, but any the
    model still writes ("(grade 5.5)", "no grade yet") get stripped here."""
    return strip_grades(_TEMPLATE_METADATA.sub("", markdown))


def _next_version(session: Session, job_id: str) -> int:
    return len(session.exec(select(CVDraft).where(CVDraft.job_id == job_id)).all()) + 1


def _seed_notes(seed: CVDraft) -> str:
    gaps = json.loads(seed.unresolved_gaps)
    lines = [
        f"Scores last time -- relevance {seed.relevance_score}/5, honesty {seed.honesty_score}/5, "
        f"impact {seed.impact_score}/5, clarity {seed.clarity_score}/5, "
        f"keyword alignment {seed.keyword_alignment_score}/5.",
        f"Feedback: {seed.overall_feedback}",
    ]
    if gaps:
        lines.append("Unresolved gaps flagged: " + "; ".join(gaps))
    return "\n".join(lines)


def job_framing(session: Session, job: Job) -> tuple[str, str]:
    """(archetype slug, framing) for a single job: its primary archetype's market framing."""
    from src.cv.library import _row_for, framing, primary_archetype

    archetype = primary_archetype(session, job.id)
    row = _row_for(session, archetype.id) if archetype else None
    if archetype is None or row is None:
        raise ValueError("This job has no archetype yet: assign one on the job page first.")
    return archetype.slug, framing(row)


def generate_cv(session: Session, job: Job, seed: CVDraft | None = None) -> CVDraft:
    slug, job_frame = job_framing(session, job)
    initial_state = CVDraftState(
        job_id=job.id,
        job_title=job.title,
        job_company=job.company,
        job_location=job.location,
        job_level=job.level,
        job_description=job.description,
        archetype_slug=slug,
        framing=job_frame,
        seed_draft=seed.draft_markdown if seed else None,
        seed_notes=_seed_notes(seed) if seed else None,
    )
    result = GRAPH.invoke(initial_state.model_dump())
    final = CVDraftState.model_validate(result)

    total_tokens = sum(log.input_tokens + log.output_tokens for log in final.node_logs)
    total_latency = sum(log.latency_ms for log in final.node_logs)
    models_used = ",".join(sorted({log.model for log in final.node_logs})) or None

    cv_draft = CVDraft(
        job_id=job.id,
        archetype_slug=slug,
        draft_markdown=_strip_template_metadata(final.draft_markdown or ""),
        attempt_count=final.attempt_count,
        verdict=final.verdict or "revise",
        relevance_score=final.relevance_score,
        honesty_score=final.honesty_score,
        impact_score=final.impact_score,
        clarity_score=final.clarity_score,
        keyword_alignment_score=final.keyword_alignment_score,
        overall_feedback=final.overall_feedback,
        unresolved_gaps=json.dumps(final.unresolved_gaps),
        is_regenerate=seed is not None,
        model_used=models_used,
        tokens=total_tokens,
        latency_ms=total_latency,
    )
    cv_draft.file_path = export_cv_draft(job, cv_draft, _next_version(session, job.id))
    return cv_draft


MANUAL_EDIT = "manual-edit"


def save_manual_edit(session: Session, job: Job, base: CVDraft, markdown: str) -> CVDraft:
    """A hand-edited CV becomes a new version, so the LLM's draft stays in the
    history. Scores and feedback are carried over from the version it was
    edited from (they describe that text, which the UI says)."""
    cv_draft = CVDraft(
        job_id=job.id,
        archetype_slug=base.archetype_slug,
        draft_markdown=markdown,
        attempt_count=base.attempt_count,
        verdict=base.verdict,
        relevance_score=base.relevance_score,
        honesty_score=base.honesty_score,
        impact_score=base.impact_score,
        clarity_score=base.clarity_score,
        keyword_alignment_score=base.keyword_alignment_score,
        overall_feedback=base.overall_feedback,
        unresolved_gaps=base.unresolved_gaps,
        is_regenerate=False,
        model_used=MANUAL_EDIT,
        tokens=0,
        latency_ms=0,
    )
    cv_draft.file_path = export_cv_draft(job, cv_draft, _next_version(session, job.id))
    return cv_draft


def _print_result(job: Job, cv_draft: CVDraft):
    hit_ceiling = cv_draft.verdict != "approve" and cv_draft.attempt_count >= MAX_ATTEMPTS
    status = "approved" if cv_draft.verdict == "approve" else ("maxed-out" if hit_ceiling else "revise")
    print(
        f"{job.company} -- {job.title} :: {status} after {cv_draft.attempt_count} attempt(s) "
        f"(honesty={cv_draft.honesty_score}, relevance={cv_draft.relevance_score}) -> {cv_draft.file_path}"
    )


def run_one(job_id: str, regenerate: bool):
    engine = init_db(get_engine())
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            print(f"No job with id {job_id}")
            return
        seed = None
        if regenerate:
            seed = session.exec(
                select(CVDraft).where(CVDraft.job_id == job_id).order_by(CVDraft.created_at.desc())
            ).first()
            if seed is None:
                print(f"No existing CV draft for {job_id} -- run without --regenerate first")
                return
        cv_draft = generate_cv(session, job, seed=seed)
        session.add(cv_draft)
        session.commit()
        _print_result(job, cv_draft)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--regenerate", action="store_true")
    args = parser.parse_args()
    run_one(args.job_id, args.regenerate)


if __name__ == "__main__":
    main()
