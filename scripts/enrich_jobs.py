"""Build role cards, skills and embeddings for jobs (pipeline revamp, Phase 1).

Usage:
    python scripts/enrich_jobs.py --missing            # every job without a current role card or embedding
    python scripts/enrich_jobs.py --job-id <id> [--force]
    python scripts/enrich_jobs.py --missing --limit 5  # try a few first

Role cards use Sonnet (~2-3 cents per job); embeddings run locally.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from src.db import Embedding, Job, RoleCard, get_engine, init_db  # noqa: E402
from src.enrich import enrich_job  # noqa: E402
from src.enrich.embeddings import EMBED_MODEL  # noqa: E402
from src.enrich.enrich import ROLE_CARD_PROMPT_VERSION  # noqa: E402


def _needs_work(session: Session, job: Job) -> bool:
    card = session.get(RoleCard, job.id)
    if card is None or card.prompt_version != ROLE_CARD_PROMPT_VERSION:
        return bool((job.description or "").strip())
    emb = session.get(Embedding, job.id)
    return emb is None or emb.model != EMBED_MODEL


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--missing", action="store_true")
    group.add_argument("--job-id")
    parser.add_argument("--force", action="store_true", help="Re-extract the role card even if current")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    engine = init_db(get_engine())
    with Session(engine) as session:
        if args.job_id:
            jobs = [session.get(Job, args.job_id)]
            if jobs[0] is None:
                sys.exit(f"No job {args.job_id}")
        else:
            jobs = [j for j in session.exec(select(Job).order_by(Job.first_seen.desc())).all() if _needs_work(session, j)]
        if args.limit:
            jobs = jobs[: args.limit]
        print(f"{len(jobs)} job(s) to enrich")
        problems = []
        for i, job in enumerate(jobs, 1):
            try:
                result = enrich_job(session, job, force=args.force)
                session.commit()
            except Exception as exc:  # keep going: one bad posting shouldn't stop a backfill
                session.rollback()
                problems.append((job.id, str(exc)))
                print(f"[{i}/{len(jobs)}] ERROR {job.company} — {job.title}: {exc}")
                continue
            flags = []
            if result.get("skipped"):
                flags.append(result["skipped"])
            if result.get("language_ok") is False:
                flags.append("NOT ENGLISH")
            print(f"[{i}/{len(jobs)}] {job.company} — {job.title} :: {result.get('quality', '-')} {' '.join(flags)}")
        if problems:
            print(f"\n{len(problems)} error(s); re-run with --missing to retry them.")


if __name__ == "__main__":
    main()
