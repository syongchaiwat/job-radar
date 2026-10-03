"""Load the CV template for prompt injection.

Deliberately separate from profile_context.py: that module's whole docstring
promise is "reads straight from profile/, the synced copy" -- cv_profile/ is
the opposite, a repo-local, gitignored folder (real contact details) that
scripts/sync_profile.py only seeds once and never overwrites (profile/ is
destructively rmtree'd and recopied on every sync run). Mixing
the two would make profile_context.py's docstring inaccurate.

One template, not one per theme: theme-specific content lives in
profile/projects.md instead (loaded via profile_context.load_projects()),
selected and phrased fresh per generation rather than pre-baked into five
near-duplicate files.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CV_PROFILE_DIR = REPO_ROOT / "cv_profile"


def load_cv_template() -> str:
    return (CV_PROFILE_DIR / "cv_template.md").read_text()
