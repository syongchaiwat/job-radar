"""Load per-theme retrieval keywords from profile/themes/*.md.

Keeps ingestion queries in sync with the theme files automatically: edit the
"Retrieval keywords" line in the profile source, re-run sync_profile.py, and ingestion
picks up the change with no code edit.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
THEMES_DIR = REPO_ROOT / "profile" / "themes"

# Location words that ride along in the keywords line but belong in a "where"
# param, not a job-title/skill search term.
LOCATION_STOPWORDS = {
    "zurich", "zug", "geneva", "lugano", "basel", "switzerland",
    "remote switzerland", "vaud",
}


def _extract_theme_id(text: str) -> str:
    m = re.search(r'theme_id:\s*"?([\w]+)"?', text)
    return m.group(1) if m else "unknown"


def _extract_keywords_line(text: str) -> str:
    m = re.search(r"## Retrieval keywords\s*\n(.+)", text)
    return m.group(1).strip() if m else ""


def load_theme_keywords() -> dict[str, list[str]]:
    """Return {theme_id: [job-title/skill keywords, location words stripped]}."""
    if not THEMES_DIR.is_dir():
        raise FileNotFoundError(f"{THEMES_DIR} not found. Run scripts/sync_profile.py first.")

    themes: dict[str, list[str]] = {}
    for path in sorted(THEMES_DIR.glob("*.md")):
        text = path.read_text()
        theme_id = _extract_theme_id(text)
        raw = _extract_keywords_line(text)
        terms = [t.strip() for t in raw.split(",") if t.strip()]
        job_terms = [t for t in terms if t.lower() not in LOCATION_STOPWORDS]
        themes[theme_id] = job_terms
    return themes
