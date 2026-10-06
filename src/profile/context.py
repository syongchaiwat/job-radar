"""Load profile context (filters, constraints, lanes, projects, coursework) for prompt injection.

Reads straight from profile/ -- the copy synced from PROFILE_SOURCE_DIR (or
examples/) -- so a profile edit takes effect on the next sync_profile.py run,
no code edit needed.
"""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_DIR = REPO_ROOT / "profile"

def load_filters() -> str:
    return (PROFILE_DIR / "filters.md").read_text()


def load_constraints() -> str:
    """constraints.md plus lanes.md (the lanes live only there)."""
    text = (PROFILE_DIR / "constraints.md").read_text()
    lanes = PROFILE_DIR / "lanes.md"
    return text + ("\n\n" + lanes.read_text() if lanes.exists() else "")


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


def load_motivation() -> str:
    """Why the candidate is looking, in their words (cover letters). Optional file."""
    path = PROFILE_DIR / "motivation.md"
    return path.read_text() if path.exists() else "(no motivation notes: keep the motivation to what the posting and the lane support)"


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


_CV_ONLY = ("- **Role angles", "- **Framing", "- **TODO")


def _projects_for_screening() -> str:
    """Project database without the CV-drafting hints (role angles, framing notes, TODOs)."""
    out, skipping = [], False
    for line in load_projects_for_cv().splitlines():
        if line.startswith(_CV_ONLY):
            skipping = True
            continue
        if skipping and line.startswith("  "):  # indented sub-bullets of a skipped field
            continue
        skipping = False
        out.append(line)
    return "\n".join(out)


def _cv_facts() -> str:
    """Education, skills and languages from the CV template (degree status, SQL, German level...)."""
    from src.profile.cv_template import load_cv_template

    try:
        text = load_cv_template()
    except FileNotFoundError:
        return ""
    keep = [m.group(0).strip() for m in re.finditer(r"^## (?:Education|Technical Skills|Languages)\b.*?(?=^## |\Z)", text, re.M | re.S)]
    return "\n\n".join(keep)


def candidate_profile() -> str:
    """What screening judges a job against: CV facts, the project database and coursework (no grades)."""
    return f"{strip_grades(_cv_facts())}\n\n{_projects_for_screening()}\n\n## Coursework\n{load_coursework_for_cv()}"
