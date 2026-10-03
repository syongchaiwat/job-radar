"""One-off backfill: compute a card blurb for every existing Screening row
that doesn't have one yet (jobs screened before generate_blurb_node existed).
Reuses generate_blurb_node directly so backfilled blurbs are generated
identically to ones the live pipeline produces -- not a separate prompt path.

Run once after the blurb/breakdown migration: python scripts/backfill_blurbs.py
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from sqlmodel import Session, select  # noqa: E402

from src.db import Job, Screening, get_engine, init_db  # noqa: E402
from src.pipeline.nodes import generate_blurb_node  # noqa: E402
from src.pipeline.schemas import PipelineState  # noqa: E402


def backfill():
    engine = init_db(get_engine())
    with Session(engine) as session:
        todo = session.exec(select(Screening).where(Screening.blurb.is_(None))).all()
        print(f"{len(todo)} screening rows missing a blurb")
        for i, sc in enumerate(todo, 1):
            job = session.get(Job, sc.job_id)
            if job is None:
                continue
            state = PipelineState(
                job_id=job.id,
                title=job.title,
                company=job.company,
                location=job.location,
                description=job.description,
                level=job.level,
            )
            result = generate_blurb_node(state)
            sc.blurb = result["blurb"]
            session.add(sc)
            session.commit()
            print(f"[{i}/{len(todo)}] {job.company} — {job.title}: {sc.blurb}")


if __name__ == "__main__":
    backfill()
