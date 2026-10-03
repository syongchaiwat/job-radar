# CLAUDE.md — job-radar

## What this repo is

A job-search assistant: ingest Swiss job postings, screen and score them against a candidate profile with a LangGraph pipeline, triage them on a FastAPI + HTMX dashboard, and draft tailored CVs with a draft/critique agent loop. Built like production code: structured outputs, evals, guardrails, observability.

## Data boundary

The candidate's data never lives in git. `profile/`, `cv_profile/`, `data/` (DB + seed jobs) and `evals/results/` are gitignored working copies, filled by `scripts/sync_profile.py` from `PROFILE_SOURCE_DIR` (a private folder, see `examples/README.md`) or, if unset, from the fictional example profile in `examples/`. Edit the source, not the working copies. Personal setup notes go in `CLAUDE.local.md` (gitignored).

`plan.md` is the build log: check it before starting new work and update it as phases complete.

## Conventions

- Python 3.13, venv at `.venv/`
- SQLModel for the DB (`src/db.py`): `Job`, `GroundTruth`, `Screening`, `Tracking`, `CVDraft`
- Structured outputs everywhere in the LangGraph pipelines, no free-text parsing of LLM output
- Prompts live in versioned files under `src/pipeline/prompts/`, not inline strings, so they're diffable and eval-able
- Deterministic guardrails sit around LLM judgments (see `src/pipeline/cv_nodes.py`)
- Job dedupe key: `sha1(url)[:16]`
- Every pipeline node logs tokens + latency
- Re-run `python evals/run_eval.py --fast` after pipeline changes
