"""CLI: python -m src.screening.run --job-id <id> | --all

Runs the screening graph for one job (or every job that doesn't have a
Screening row yet) and writes the result to the DB.
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from src.db import Job, Screening, get_engine, init_db  # noqa: E402
from src.screening.graph import build_graph  # noqa: E402
from src.llm.schemas import PipelineState  # noqa: E402

GRAPH = build_graph()


def archetype_text(session: Session, job_id: str) -> str | None:
    """'Name: definition' of the job's primary archetype in the active set, if any."""
    from src.cv.library import primary_archetype

    a = primary_archetype(session, job_id)
    return f"{a.name}: {a.definition}" if a else None


def screen_job(job: Job, archetype: str | None = None) -> Screening:
    initial_state = PipelineState(
        job_id=job.id,
        title=job.title,
        company=job.company,
        location=job.location,
        description=job.description,
        level=job.level,
        archetype=archetype,
        manual=job.source == "manual",
    )
    result = GRAPH.invoke(initial_state.model_dump())
    final = PipelineState.model_validate(result)

    # normalize_node backfills title/company for manual URL-paste jobs that
    # were added without them -- write that back onto the Job row itself,
    # since PipelineState is transient and otherwise never persisted.
    job.title = final.title
    job.company = final.company

    total_tokens = sum(log.input_tokens + log.output_tokens for log in final.node_logs)
    total_latency = sum(log.latency_ms for log in final.node_logs)
    models_used = ",".join(sorted({log.model for log in final.node_logs})) or None

    return Screening(
        job_id=job.id,
        decision=final.decision or "keep",
        filter_reasons=json.dumps(final.filter_reasons),
        blurb=final.blurb,
        match_level=final.match_level,
        match_rationale=final.match_rationale,
        gaps=json.dumps(final.gaps),
        model_used=models_used,
        tokens=total_tokens,
        latency_ms=total_latency,
    )


def _print_result(job: Job, screening: Screening):
    print(
        f"{job.company} — {job.title} :: {screening.decision}/{screening.match_level} "
        f"({screening.tokens} tok, {screening.latency_ms:.0f}ms)"
    )


def run_one(job_id: str):
    engine = init_db(get_engine())
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            print(f"No job with id {job_id}")
            return
        screening = screen_job(job, archetype_text(session, job.id))
        session.add(screening)
        session.commit()
        _print_result(job, screening)


def run_all():
    engine = init_db(get_engine())
    with Session(engine) as session:
        already_screened = set(session.exec(select(Screening.job_id)).all())
        todo = [j for j in session.exec(select(Job)).all() if j.id not in already_screened]
        print(f"{len(todo)} unscreened jobs")
        for i, job in enumerate(todo, 1):
            screening = screen_job(job, archetype_text(session, job.id))
            session.add(screening)
            session.commit()
            print(f"[{i}/{len(todo)}] ", end="")
            _print_result(job, screening)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--job-id")
    group.add_argument("--all", action="store_true")
    args = parser.parse_args()
    run_all() if args.all else run_one(args.job_id)


if __name__ == "__main__":
    main()
