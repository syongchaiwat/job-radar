"""Load profile context (filters, theme files, constraints) for prompt injection.

Reads straight from profile/ -- the copy synced from PROFILE_SOURCE_DIR (or
examples/) -- so a profile edit takes effect on the next sync_profile.py run,
no code edit needed.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_DIR = REPO_ROOT / "profile"

THEME_FILES = {
    "1": "theme-1-quant-finance-risk.md",
    "2": "theme-2-agentic-ai-llm.md",
    "3a": "theme-3a-core-ml.md",
    "3b": "theme-3b-data-backend-infra.md",
    "4": "theme-4-business-analyst.md",
}


def load_filters() -> str:
    return (PROFILE_DIR / "filters.md").read_text()


def load_constraints() -> str:
    return (PROFILE_DIR / "constraints.md").read_text()


def load_projects() -> str:
    """Rich project database (work/study/personal, tagged for the CV-drafting agent)."""
    return (PROFILE_DIR / "projects.md").read_text()


_GRADE_SUFFIX = re.compile(r"\s+[—–-]\s+\d(?:\.\d+)?(?=\s|$)")
_GRADE_PHRASE = re.compile(r"\s*\((?:grade|no grade)[^)]*\)|,?\s*\bno grade yet\b|\b[Gg]rade \d(?:\.\d+)?(?:/\d(?:\.\d+)?)?[,.]?\s*", re.I)


def strip_grades(text: str, course_list: bool = False) -> str:
    """CVs never show individual course grades (only the degree GPA, which lives
    in cv_template.md), so the CV prompts get grade-free source text. The
    "Course — 5.5" suffix form is only stripped from the course list, where it
    can't be mistaken for a real number in a project's results."""
    lines = text.splitlines()
    if course_list:
        lines = [_GRADE_SUFFIX.sub("", line) for line in lines]
    return "\n".join(_GRADE_PHRASE.sub("", line) for line in lines)


def load_coursework() -> str:
    """Flat course list by degree -- citable in Education without a full project behind it."""
    return (PROFILE_DIR / "coursework.md").read_text()


def load_coursework_for_cv() -> str:
    """Coursework without grades; each ongoing course is tagged "(in progress)"
    on its own line, the exact wording the CV should use."""
    out, in_progress = [], False
    for line in strip_grades(load_coursework(), course_list=True).splitlines():
        if line.startswith("**"):
            in_progress = "in progress" in line.lower()
        elif in_progress and line.startswith("- "):
            # drop internal notes like "(core AI elective)": the CV wording is just "(in progress)"
            line = re.sub(r"\s*\([^)]*\)$", "", line) + " (in progress)"
        out.append(line)
    return "\n".join(out)


def load_projects_for_cv() -> str:
    return strip_grades(load_projects())


def load_theme(theme_code: str) -> str:
    """Full theme file for a single theme code (used once a job is classified)."""
    filename = THEME_FILES.get(theme_code)
    if not filename:
        return "(no matching theme profile)"
    return (PROFILE_DIR / "themes" / filename).read_text()


def load_all_themes_summary() -> str:
    """Compact summary of all 5 themes for classify_theme -- avoids dumping 5 full files."""
    themes_dir = PROFILE_DIR / "themes"
    parts = [_extract_summary(path.read_text()) for path in sorted(themes_dir.glob("*.md"))]
    return "\n\n".join(parts)


def _extract_summary(text: str) -> str:
    theme_id = re.search(r'theme_id:\s*"?([\w]+)"?', text)
    name = re.search(r"^name:\s*(.+)$", text, re.MULTILINE)
    # [^\n]+ (not DOTALL-affected) keeps the title match on one line; only the
    # capture group needs DOTALL, and being non-greedy stops at the first \n\n.
    intro = re.search(r"^# [^\n]+\n\n(.+?)(?:\n\n|\Z)", text, re.MULTILINE | re.DOTALL)
    theme_label = theme_id.group(1) if theme_id else "?"
    name_label = name.group(1).strip() if name else ""
    intro_text = intro.group(1).strip() if intro else ""
    return f"**Theme {theme_label}: {name_label}**\n{intro_text}"
