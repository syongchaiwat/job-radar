"""Lane assessment for jobs (pipeline revamp, Phase 5): lane, eligibility, lane value, deadline.

Usage:
    python scripts/assess_lanes.py --missing     # jobs without an assessment, or assessed against an older lanes.md
    python scripts/assess_lanes.py --job-id <id>
Sonnet, ~1-2 cents per job.
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from src.db import Job, LaneAssessment, RoleCard, get_engine, init_db  # noqa: E402
from src.lanes.core import assess_job, lanes_hash  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--missing", action="store_true")
    g.add_argument("--job-id")
    args = parser.parse_args()
    engine = init_db(get_engine())
    with Session(engine) as session:
        if args.job_id:
            jobs = [session.get(Job, args.job_id)]
        else:
            h = lanes_hash()
            jobs = [j for j, _ in session.exec(select(Job, RoleCard).where(Job.id == RoleCard.job_id)).all()
                    if (a := session.get(LaneAssessment, j.id)) is None or a.lanes_hash != h]
        print(f"{len(jobs)} job(s) to assess")
        for i, job in enumerate(jobs, 1):
            try:
                a = assess_job(session, job)
                session.commit()
                print(f"[{i}/{len(jobs)}] {job.company} — {job.title} :: {a.lane} · eligible {a.eligible} · value {a.value_score:.2f}" + (f" · deadline {job.deadline}" if job.deadline else ""))
            except Exception as exc:
                session.rollback()
                print(f"[{i}/{len(jobs)}] ERROR {job.company} — {job.title}: {exc}")


if __name__ == "__main__":
    main()
