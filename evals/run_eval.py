"""Eval harness: score the screening pipeline against labeled ground truth.

Usage:
    python evals/run_eval.py            # fresh re-screen every GroundTruth job, then score (default)
    python evals/run_eval.py --fast     # score whatever's already in the DB, no re-screening

Default is a fresh re-screen: GroundTruth-labeled jobs aren't run often enough
for that cost to matter, and scoring whatever's already in the DB risks a
silent patchwork of different pipeline versions across rows (this happened
for real on 18-19 Aug: 22 of 24 seed jobs reflected one prompt version, 2
reflected a newer one, with nothing marking the difference). --fast exists
only for iterating on this script's own scoring logic without waiting.

GroundTruth is not just the original 24 seed jobs forever -- source/created_at
track provenance, so this script reads GroundTruth generically and will pick
up future user corrections (once the Phase 4 dashboard can write them) with
no changes needed here.

Writes evals/results/{date}.json (full per-job comparison + summary metrics)
and prints a scorecard to stdout.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")

from sqlmodel import Session, delete, select  # noqa: E402

from src.db import GroundTruth, Job, Screening, get_engine, init_db  # noqa: E402
from src.pipeline.llm_config import PROVIDER, model_label  # noqa: E402
from src.pipeline.run import screen_job  # noqa: E402

RESULTS_DIR = REPO_ROOT / "evals" / "results"

CANONICAL_FIT_LEVELS = {"strong", "good", "moderate", "stretch"}
FIT_ORDER = ["stretch", "moderate", "good", "strong"]  # weakest to strongest


def normalize_fit(fit_raw: str) -> str | None:
    """Extract the leading canonical fit word, e.g. 'moderate (German gate)' -> 'moderate'.
    Returns None for non-canonical ground truth (e.g. 'accessible', 'weak-moderate',
    'no fit') -- those use a different axis (entry-barrier, not fit quality) and
    aren't comparable to match_level on the strong/good/moderate/stretch scale."""
    leading = re.split(r"[(,]", fit_raw.strip())[0].strip().lower()
    return leading if leading in CANONICAL_FIT_LEVELS else None


def theme_matches(ground_truth_theme: str, screening_theme: str | None, decision: str) -> bool:
    """'none' ground truth matches either an exclude or a theme=none/None result --
    both represent 'this job doesn't fit any theme', just reached via different
    branches of the graph (filter_gate exclude vs classify_theme=none)."""
    if ground_truth_theme == "none":
        return decision == "exclude" or screening_theme in (None, "none")
    return screening_theme == ground_truth_theme


# NOTE on excluded-with-real-theme: GroundTruth only records theme + fit, not an
# explicit "should this be excluded" judgment. A job can genuinely belong to a
# real theme (topically) AND be correctly excluded by a filter rule (years
# experience, visa, German) -- those are two independent layers, not one. So
# this list is a review shortlist, not a confirmed-bug count: checked by hand on
# 20 Aug, 1 of 3 flagged here (Artificialy) was an actual bug; Lobby and P&G were
# both correctly excluded (real 8+ years / real EU-EFTA restriction). A cleaner
# fix would be adding an explicit expected_decision label to GroundTruth -- left
# as a future enhancement, not built now.


def run(fast: bool):
    engine = init_db(get_engine())

    with Session(engine) as session:
        gt_rows = session.exec(select(GroundTruth)).all()
        if not gt_rows:
            print("No GroundTruth rows found. Run scripts/seed_db.py first.")
            return

        if not fast:
            job_ids = [gt.job_id for gt in gt_rows]
            session.exec(delete(Screening).where(Screening.job_id.in_(job_ids)))
            session.commit()
            print(f"Fresh re-screening {len(gt_rows)} ground-truth jobs (this takes a while)...")
            for i, gt in enumerate(gt_rows, 1):
                job = session.get(Job, gt.job_id)
                screening = screen_job(job)
                session.add(screening)
                session.commit()
                print(f"  [{i}/{len(gt_rows)}] {job.company} — {job.title}")
            print()

        results = []
        for gt in gt_rows:
            job = session.get(Job, gt.job_id)
            screening = session.exec(
                select(Screening).where(Screening.job_id == gt.job_id).order_by(Screening.created_at.desc())
            ).first()

            if screening is None:
                results.append(
                    {
                        "job_id": gt.job_id,
                        "company": job.company,
                        "title": job.title,
                        "error": "not screened (run without --fast, or screen it manually first)",
                    }
                )
                continue

            # A forced theme (set via the dashboard's "Your labels" or --force-theme)
            # bypasses classify_theme, so it would score itself correct -- leave
            # those out of theme accuracy. Match/gaps still ran, so they still count.
            theme_forced = bool(job.forced_theme)
            theme_ok = None if theme_forced else theme_matches(gt.theme_code, screening.theme, screening.decision)
            excluded_with_real_theme = gt.theme_code != "none" and screening.decision == "exclude"

            expected_fit = normalize_fit(gt.fit_raw)
            match_ok = match_within_one = None
            if expected_fit and screening.match_level and screening.decision != "exclude":
                match_ok = screening.match_level == expected_fit
                try:
                    dist = abs(FIT_ORDER.index(screening.match_level) - FIT_ORDER.index(expected_fit))
                    match_within_one = dist <= 1
                except ValueError:
                    match_within_one = None

            results.append(
                {
                    "job_id": gt.job_id,
                    "company": job.company,
                    "title": job.title,
                    "ground_truth_theme": gt.theme_code,
                    "ground_truth_fit": gt.fit_raw,
                    "ground_truth_source": gt.source,
                    "decision": screening.decision,
                    "screening_theme": screening.theme,
                    "match_level": screening.match_level,
                    "theme_forced": theme_forced,
                    "theme_ok": theme_ok,
                    "excluded_with_real_theme": excluded_with_real_theme,
                    "expected_fit": expected_fit,
                    "match_ok": match_ok,
                    "match_within_one": match_within_one,
                }
            )

    _report(results)


def _report(results: list[dict]):
    scored = [r for r in results if "error" not in r]
    errors = [r for r in results if "error" in r]

    n = len(scored)
    theme_scored = [r for r in scored if r["theme_ok"] is not None]
    theme_correct = sum(1 for r in theme_scored if r["theme_ok"])
    n_theme = len(theme_scored)
    review_list = [r for r in scored if r["excluded_with_real_theme"]]

    matchable = [r for r in scored if r["match_ok"] is not None]
    match_exact = sum(1 for r in matchable if r["match_ok"])
    match_within_one = sum(1 for r in matchable if r["match_within_one"])

    print("=" * 60)
    print("EVAL RESULTS")
    print("=" * 60)
    print(f"Provider: {PROVIDER} (fast={model_label('fast')}, deep={model_label('deep')})")
    print(f"Scored: {n}/{len(results)}" + (f"  ({len(errors)} errors)" if errors else ""))
    print()
    print(f"Theme accuracy:        {theme_correct}/{n_theme}  ({100*theme_correct/n_theme:.0f}%)" if n_theme else "Theme accuracy: n/a")
    if n_theme < n:
        print(f"    ({n - n_theme} jobs skipped: theme forced by the user, classifier didn't run)")
    print(
        f"Excluded w/ real theme: {len(review_list)}/{n}  "
        f"(review list, NOT a bug count -- some are legitimately excluded by a filter rule)"
    )
    for r in review_list:
        print(f"    - {r['company']} — {r['title']}")
    if matchable:
        print(
            f"Match-level exact:     {match_exact}/{len(matchable)}  ({100*match_exact/len(matchable):.0f}%)"
        )
        print(
            f"Match-level within-1:  {match_within_one}/{len(matchable)}  "
            f"({100*match_within_one/len(matchable):.0f}%)"
        )
        skipped = n - len(matchable)
        if skipped:
            print(f"    ({skipped} jobs skipped: non-canonical ground truth fit label or excluded)")
    for r in errors:
        print(f"  ERROR {r['company']} — {r['title']}: {r['error']}")
    print("=" * 60)

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "provider": PROVIDER,
        "model_fast": model_label("fast"),
        "model_deep": model_label("deep"),
        "summary": {
            "scored": n,
            "theme_accuracy": theme_correct / n_theme if n_theme else None,
            "excluded_with_real_theme_count": len(review_list),
            "match_exact": match_exact / len(matchable) if matchable else None,
            "match_within_one": match_within_one / len(matchable) if matchable else None,
        },
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\nWrote {out_path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="Score existing DB rows instead of re-screening")
    args = parser.parse_args()
    run(fast=args.fast)


if __name__ == "__main__":
    main()
