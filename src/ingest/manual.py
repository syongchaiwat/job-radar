"""Manual job entry: paste a URL (+ optional description) instead of scraping it.

LinkedIn has no public API and blocks unauthenticated scraping, so this is the
deliberate replacement for browsing LinkedIn and pasting URLs by hand. Title
and company are optional -- if left blank, the Phase 2 pipeline's normalize
step fills them in from the pasted description text.
"""
from typing import Optional

from sqlmodel import Session

from src.db import Job
from src.ingest.dedupe import job_id


def build_job(
    url: str,
    description: Optional[str] = None,
    title: Optional[str] = None,
    company: Optional[str] = None,
    location: Optional[str] = None,
    theme_hint: Optional[str] = None,
) -> dict:
    return {
        "source": "manual",
        "url": url.strip(),
        "company": company or "Unknown",
        "title": title or "",
        "description": description,
        "location": location,
        "level": None,
        "posted_at": None,
        "theme_hint": theme_hint,
    }


def create_manual_job(session: Session, raw: dict, forced_theme: Optional[str] = None) -> Job:
    """Insert a build_job() dict as a Job row. Caller checks is_duplicate first.
    Shared by scripts/add_manual_job.py and the dashboard's "Add a job" form."""
    job = Job(
        id=job_id(raw["url"]),
        source=raw["source"],
        url=raw["url"],
        company=raw["company"],
        title=raw["title"],
        description=raw.get("description"),
        location=raw.get("location"),
        theme_hint=raw.get("theme_hint"),
        forced_theme=forced_theme,
    )
    session.add(job)
    session.commit()
    return job
