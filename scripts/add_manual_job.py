"""Add a job posting by hand: give the URL, everything else is optional.

If you don't pass --description, this tries to auto-fetch and extract the
posting from the URL itself (title/company/location/description) -- see
src/ingest/url_fetch.py. That only works for sites that don't block plain
requests; LinkedIn and any site behind bot-detection (confirmed: DataDome on
some Swiss job boards) will fail the auto-fetch by design, since defeating
that isn't something this tool does. When it fails, fall back to pasting the
description yourself, same as before.

Usage:
    python scripts/add_manual_job.py <url>                          # tries auto-fetch
    python scripts/add_manual_job.py <url> --description "paste the job text here"
    python scripts/add_manual_job.py <url> --title "..." --company "..." --location "Zurich"
"""
import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from sqlmodel import Session  # noqa: E402

from src.db import get_engine, init_db  # noqa: E402
from src.ingest.dedupe import is_duplicate  # noqa: E402
from src.ingest.manual import build_job, create_manual_job  # noqa: E402
from src.ingest.url_fetch import fetch_and_extract  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--description", default=None, help="Paste the job description text")
    parser.add_argument("--title", default=None)
    parser.add_argument("--company", default=None)
    parser.add_argument("--location", default=None)
    parser.add_argument("--no-fetch", action="store_true", help="Skip auto-fetch even if --description is omitted")
    args = parser.parse_args()

    description, title, company, location = args.description, args.title, args.company, args.location
    if description is None and not args.no_fetch:
        print("No --description given, trying to auto-fetch the posting...")
        fetched = fetch_and_extract(args.url)
        if fetched is None:
            print("Auto-fetch didn't work for this URL (blocked, bot-protected, or unreachable).")
            print("Falling back to a bare entry -- pass --description yourself, or edit later.")
        else:
            description = fetched["description"]
            title = title or fetched["title"]
            company = company or fetched["company"]
            location = location or fetched["location"]
            print(f"Auto-fetched: {fetched['company']} — {fetched['title']}")

    raw = build_job(
        args.url,
        description=description,
        title=title,
        company=company,
        location=location,
    )

    engine = init_db(get_engine())
    with Session(engine) as session:
        if is_duplicate(session, raw["url"]):
            print("Already in the DB, skipped.")
            return
        job = create_manual_job(session, raw)
        label = job.title or "(untitled, needs Phase 2 normalize)"
        print(f"Added: {job.company} — {label}")


if __name__ == "__main__":
    main()
