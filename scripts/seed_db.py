"""Parse data/seed-jobs.md into the DB (Job + GroundTruth) and evals/labeled_jobs.jsonl.

Run standalone (`python scripts/seed_db.py`) to re-seed after editing seed-jobs.md,
or via sync_profile.py which calls seed() after refreshing the file from the profile source.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from sqlmodel import Session, select  # noqa: E402

from src.db import GroundTruth, Job, get_engine, init_db  # noqa: E402
from src.ingest.dedupe import job_id as _job_id  # noqa: E402

SEED_MD = REPO_ROOT / "data" / "seed-jobs.md"
SEED_DESCRIPTIONS = REPO_ROOT / "data" / "seed_descriptions.json"
LABELED_JSONL = REPO_ROOT / "evals" / "labeled_jobs.jsonl"

EXPECTED_HEADERS = ["Company", "Role", "Fit", "Level", "Location", "URL"]
SEED_SOURCE_LABEL = "seed_2026-08-12"


def _parse_table(md_text: str) -> list[dict]:
    lines = [ln for ln in md_text.splitlines() if ln.strip().startswith("|")]
    if len(lines) < 3:
        raise ValueError("No markdown table found in seed-jobs.md")

    header_cells = [c.strip() for c in lines[0].strip("|").split("|")]
    if header_cells != EXPECTED_HEADERS:
        raise ValueError(f"Unexpected table headers: {header_cells}")

    rows = []
    for line in lines[2:]:  # skip header + separator row
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != len(header_cells):
            continue
        rows.append(dict(zip(header_cells, cells)))
    return rows


def seed():
    if not SEED_MD.is_file():
        raise FileNotFoundError(f"{SEED_MD} not found. Run sync_profile.py first.")

    rows = _parse_table(SEED_MD.read_text())
    descriptions = json.loads(SEED_DESCRIPTIONS.read_text()) if SEED_DESCRIPTIONS.is_file() else {}

    engine = init_db(get_engine())
    labeled_records = []

    with Session(engine) as session:
        for row in rows:
            job_id = _job_id(row["URL"])

            existing = session.get(Job, job_id)
            job = existing or Job(id=job_id, source="seed", url=row["URL"])
            job.company = row["Company"]
            job.title = row["Role"]
            job.location = row["Location"]
            job.level = row["Level"]
            job.source = job.source or "seed"
            if job_id in descriptions:
                job.description = descriptions[job_id]
            session.add(job)

            gt = session.get(GroundTruth, job_id)
            if gt is None:
                gt = GroundTruth(
                    job_id=job_id,
                    fit_raw=row["Fit"],
                    source=SEED_SOURCE_LABEL,
                    created_at=datetime.now(timezone.utc),
                )
                session.add(gt)
            elif gt.source.startswith("seed"):
                # Still a seed label (never corrected by a user) -- safe to refresh
                # from seed-jobs.md. A user_correction source is left untouched so a
                # later dashboard correction can't be silently clobbered by a re-seed.
                gt.fit_raw = row["Fit"]
                session.add(gt)

            labeled_records.append(
                {
                    "job_id": job_id,
                    "company": row["Company"],
                    "title": row["Role"],
                    "fit_raw": row["Fit"],
                    "level": row["Level"],
                    "location": row["Location"],
                    "url": row["URL"],
                }
            )

        session.commit()

    LABELED_JSONL.parent.mkdir(exist_ok=True)
    with LABELED_JSONL.open("w") as f:
        for rec in labeled_records:
            f.write(json.dumps(rec) + "\n")

    print(f"Seeded {len(labeled_records)} jobs into {get_engine().url} and {LABELED_JSONL}")
    return labeled_records


if __name__ == "__main__":
    seed()
