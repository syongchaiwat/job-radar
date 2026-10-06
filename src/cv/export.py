"""Writes a generated CV draft to cv_drafts/ as a standalone Markdown file.

cv_drafts/, like cv_profile/, lives outside profile/ so sync_profile.py's
rmtree-and-recopy never touches it, and it's gitignored (contains the
candidate's real contact info). One file per generation run, versioned per
job so a 'regenerate' never overwrites the version it's improving on.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

from src.db import CVDraft, Job

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CV_DRAFTS_DIR = REPO_ROOT / "cv_drafts"


def _slug(text: str, max_len: int = 30) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-")


def export_cv_draft(job: Job, cv_draft: CVDraft, version: int) -> str:
    CV_DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{job.id}_{_slug(job.company)}-{_slug(job.title)}_v{version}.md"
    path = CV_DRAFTS_DIR / filename
    header = (
        "<!--\n"
        f"job: {job.company} -- {job.title} ({job.id})\n"
        f"archetype: {cv_draft.archetype_slug}\n"
        f"generated: {datetime.now(timezone.utc).isoformat()}\n"
        f"attempts: {cv_draft.attempt_count}, verdict: {cv_draft.verdict}\n"
        "-->\n\n"
    )
    path.write_text(header + cv_draft.draft_markdown)
    return str(path.relative_to(REPO_ROOT))
