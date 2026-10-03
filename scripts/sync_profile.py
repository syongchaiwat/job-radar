"""Copy the candidate profile into the repo's gitignored working folders, then seed the DB.

One-way: source -> repo. The source is PROFILE_SOURCE_DIR from .env (e.g. a
folder in a private notes vault); without it, the fictional example profile in
examples/ is used, so a fresh clone runs end to end. Never edit profile/ or
data/seed-jobs.md in the repo directly: edit the source and re-run this script.

Source layout:
    profile/                    copied over profile/ (replaced on every run)
    seed-jobs.md                copied to data/seed-jobs.md
    seed_descriptions.json      optional, copied to data/
    cv_profile/cv_template.md   optional, copied only if cv_profile/ has no template yet
"""
import os
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

EXAMPLES_DIR = REPO_ROOT / "examples"


def _source_dir() -> Path:
    configured = os.environ.get("PROFILE_SOURCE_DIR")
    if configured:
        return Path(configured).expanduser()
    print("PROFILE_SOURCE_DIR not set: using the fictional example profile in examples/")
    return EXAMPLES_DIR


def sync() -> Path:
    source = _source_dir()
    source_profile = source / "profile"
    source_seed_jobs = source / "seed-jobs.md"
    if not source_profile.is_dir():
        raise FileNotFoundError(f"Profile folder not found: {source_profile}")
    if not source_seed_jobs.is_file():
        raise FileNotFoundError(f"seed-jobs.md not found: {source_seed_jobs}")

    repo_profile = REPO_ROOT / "profile"
    shutil.rmtree(repo_profile, ignore_errors=True)
    shutil.copytree(source_profile, repo_profile)
    n_files = sum(1 for _ in repo_profile.rglob("*.md"))
    print(f"Synced profile/: {n_files} files -> {repo_profile}")

    repo_data = REPO_ROOT / "data"
    repo_data.mkdir(exist_ok=True)
    repo_seed_jobs = repo_data / "seed-jobs.md"
    shutil.copy2(source_seed_jobs, repo_seed_jobs)
    print(f"Synced seed-jobs.md -> {repo_seed_jobs}")

    source_descriptions = source / "seed_descriptions.json"
    if source_descriptions.is_file():
        shutil.copy2(source_descriptions, repo_data / "seed_descriptions.json")
        print("Synced seed_descriptions.json")

    # The CV template holds real contact details, so it's never overwritten once present.
    source_template = source / "cv_profile" / "cv_template.md"
    repo_template = REPO_ROOT / "cv_profile" / "cv_template.md"
    if source_template.is_file() and not repo_template.exists():
        repo_template.parent.mkdir(exist_ok=True)
        shutil.copy2(source_template, repo_template)
        print(f"Copied CV template -> {repo_template}")

    return repo_seed_jobs


if __name__ == "__main__":
    sync()
    from scripts.seed_db import seed

    seed()
