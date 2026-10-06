"""Phase 1 entrypoint: pull today's postings from every configured source, dedupe, store.

Run with: python scripts/ingest.py
A source with no API key configured is skipped with a warning, not a crash --
manual entry works with zero keys, and Adzuna/JSearch come online as keys are added.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from sqlmodel import Session  # noqa: E402

from src.db import Job, get_engine, init_db  # noqa: E402
from src.ingest import adzuna, jsearch, serpapi  # noqa: E402
from src.ingest.base import FetchGroup  # noqa: E402
from src.ingest.dedupe import is_duplicate, job_id  # noqa: E402
from src.ingest.search_keywords import load_search_keywords  # noqa: E402

SOURCES: list[tuple[str, FetchGroup]] = [
    ("adzuna", adzuna.fetch_group),
    ("jsearch", jsearch.fetch_group),
    ("serpapi", serpapi.fetch_group),
]


def run():
    engine = init_db(get_engine())

    fetched = added = duplicates = skipped_sources = 0

    with Session(engine) as session:
        groups = load_search_keywords(session)
        for group, keywords in groups.items():
            if not keywords:
                continue

            for source_name, fetch_fn in SOURCES:
                try:
                    raw_jobs = fetch_fn(group, keywords)
                except Exception as e:  # noqa: BLE001 -- one source failing must not abort the run
                    print(f"  [{source_name}/{group}] skipped: {e}")
                    skipped_sources += 1
                    continue

                new_here = 0
                for raw in raw_jobs:
                    fetched += 1
                    if not raw.get("url"):
                        continue
                    if is_duplicate(session, raw["url"]):
                        duplicates += 1
                        continue
                    job = Job(
                        id=job_id(raw["url"]),
                        source=raw["source"],
                        url=raw["url"],
                        company=raw["company"],
                        title=raw["title"],
                        description=raw.get("description"),
                        location=raw.get("location"),
                        level=raw.get("level"),
                        posted_at=raw.get("posted_at"),
                        search_hint=raw.get("search_hint"),
                    )
                    session.add(job)
                    added += 1
                    new_here += 1
                print(f"  [{source_name}/{group}] {len(raw_jobs)} fetched, {new_here} new")

        session.commit()

    print(
        f"\nDone: {fetched} fetched, {added} new, {duplicates} duplicates skipped, "
        f"{skipped_sources} source calls skipped (missing keys or errors)"
    )


if __name__ == "__main__":
    run()
