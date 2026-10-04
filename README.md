# job-radar

An agentic job-search assistant for the Swiss data-science and AI market: it ingests job postings, screens and scores each one against a candidate profile with a LangGraph pipeline, turns triage into a five-minute daily habit on a dashboard, and drafts a tailored CV for the jobs worth applying to, with an LLM critic, deterministic guardrails and a PDF export.

Built and used daily as a real tool, not a demo. The repo ships with a **fictional example profile** (`examples/`), so it runs end to end without anyone's personal data.

## What it does

- **Ingest:** Adzuna, SerpApi (Google Jobs) and JSearch clients, plus manual entry by URL with auto-fetch and LLM extraction. Dedupe by URL hash.
- **Screen:** a 6-node LangGraph pipeline per job: normalize → card blurb → filter gate → classify theme → score match → extract gaps. Cheap models for filtering and classification, a stronger model for match and gaps, conditional short-circuits to save tokens.
- **Triage:** FastAPI + HTMX dashboard. A review queue (unreviewed first), sorting and filters, add-a-job-by-URL, archive/shortlist, and "your labels" corrections that are stored as eval ground truth (a theme correction pins the theme and re-screens).
- **Draft CVs:** a second LangGraph with a real cycle, `draft_cv ⇄ critique_cv`, up to 3 rounds. The drafter selects and phrases entries from a tagged project database per job; the critic fact-checks every claim against the sources and scores relevance, honesty, impact, clarity and keyword fit.
- **Export:** edit the CV by hand (saved as a new version), then render it to a styled A4 PDF.

## Themes

Jobs are classified into five themes defined in `profile/themes/*.md` (strengths, gaps, story angles, retrieval keywords per theme):

1. **Quantitative Finance / Risk**
2. **Agentic AI / LLM Application Engineering**
3a. **Core ML Engineering / Data Science**
3b. **Data / Backend Infrastructure**
4. **Business / Consulting Analyst**

## Engineering highlights

- **Structured outputs everywhere.** Every LLM call returns a Pydantic schema; no free-text parsing.
- **Deterministic guardrails around LLM judgments.** The CV critic can't approve a draft whose own honesty/relevance scores are low. It can't lower honesty without quoting a fabrication that literally exists in the draft (it used to "find" tools that only appeared in the job posting). Skill groups (3-5), summary length and course grades are checked in code, not left to the prompt.
- **Grounding by construction.** The drafter may only cite tools listed in a selected project's `Tools:` field; static facts (names, dates, contact details) come from a template and are copied verbatim.
- **Evals.** `evals/run_eval.py` re-screens every labeled job and reports theme accuracy and match-level agreement. User corrections from the dashboard flow into the same ground-truth table.
- **Observability.** Every node logs model, tokens and latency.
- **Provider switch.** `LLM_PROVIDER=anthropic|ollama` swaps screening between Claude and a local model. The CV loop always runs on Claude (Sonnet drafts, Opus critiques), because a local 8B model fabricated details while its own critique approved them.
- **Cost-aware.** Screening a job takes ~8s and ~11k tokens on Claude. Bulk-ingested jobs that fail a hard filter stop before the expensive steps; hand-added jobs get a warning instead and are screened fully.

## Setup

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env               # add ANTHROPIC_API_KEY (ingestion keys optional)
python scripts/sync_profile.py     # copies the example profile into place and seeds the DB
uvicorn app.main:app --reload --port 8000   # dashboard at localhost:8000
```

PDF export needs Google Chrome installed (it prints with headless Chrome).

### Using your own profile

Your data never goes into git. Create a private folder with the same layout as `examples/` (profile files, labeled seed jobs, CV template), set `PROFILE_SOURCE_DIR` to it in `.env`, and re-run `python scripts/sync_profile.py`. The working copies (`profile/`, `cv_profile/`, `data/`, `evals/results/`) are gitignored. See [`examples/README.md`](examples/README.md).

| File | Used for |
|---|---|
| `profile/themes/*.md` | Per-theme strengths, gaps, story angles, retrieval keywords (screening + CV framing) |
| `profile/filters.md`, `constraints.md` | Exclude/flag rules, timeline and language constraints (screening) |
| `profile/projects.md` | Project database: each piece of work tagged with `Type`, `Source`, explicit `Tools`, methodology and results (CV drafting) |
| `profile/coursework.md` | Courses by degree (CV drafting, cited only to fill gaps; grades are stripped automatically) |
| `cv_profile/cv_template.md` | Static CV facts: contact details, degrees, employers and dates, baseline skills, languages, awards |
| `cv_profile/photo.jpg` | Optional photo for the PDF |

## Usage

**Daily ingest + screening:**
```bash
python scripts/ingest.py           # fetch new postings from all configured sources
python -m src.pipeline.run --all   # screen every job without a screening yet
```

**Add a job by hand:** paste the URL into **Add a job** on the board and click **Add & screen**. If the site blocks fetching, a box appears to paste the description. CLI equivalent:
```bash
python scripts/add_manual_job.py "<url>"                                  # tries to auto-fetch the posting
python scripts/add_manual_job.py "<url>" --description "<pasted text>"    # if the site blocks fetching
python scripts/add_manual_job.py "<url>" --force-theme 1                  # pin a theme
python -m src.pipeline.run --all
```

**Role cards and market data** (pipeline revamp, Phase 1): every job gets a role card, a normalized English summary with canonical skills and an embedding, used for archetypes and market stats. Jobs added from the board get one automatically; for everything else:
```bash
python scripts/enrich_jobs.py --missing       # role cards + skills + embeddings for jobs that lack them
```
Mark postings worth learning from as **market data** (◇ on each card, or **Select jobs** for bulk), independent of whether you apply. New skill names land as *pending* on the **Skills** page: approve them, or merge duplicates so they become aliases.

**Archetypes** (Phase 2): the **Classify** page runs a rework over your market-data jobs (stable clustering + an LLM taxonomy, reconciled by Opus), shows the draft with quality signals and a map, and lets you rename, merge, split or move jobs before confirming it as a new versioned set. New jobs are matched to the active set automatically. CLI: `python scripts/archetypes.py status|seed-v0|rework`.

**Market** (Phase 3): per archetype, which skills its market-data jobs ask for, your profile coverage, strengths (with the projects/courses that prove them) and gaps, plus LLM next-step suggestions and a to-do list.

**Review and correct:** on a job's page, **Archive** or **Shortlist**; **Your labels** records your theme and match (a different theme pins it and re-screens). A wrong description can be replaced and re-screened from the same page.

**Generate a CV:** **Prepare CV** on the job page, or `python -m src.pipeline.cv_run --job-id <id>` (`--regenerate` revises the latest draft). Drafts land in `cv_drafts/` with the verdict, rubric scores, feedback and unresolved gaps. When a gap is something the candidate really has, add it to the profile source, sync, and regenerate. Always read a generated CV before sending it.

**Edit and export:** **Edit** opens the Markdown (saving creates a new version); **Download PDF** renders the latest version with `src/pipeline/cv_style.css`, tightening spacing to fit two pages before ever spilling onto a third. CLI: `python scripts/cv_pdf.py cv_drafts/<draft>.md`.

## Architecture

```
ingest: Adzuna + SerpApi + JSearch + manual (URL auto-fetch), dedupe by URL hash
  -> screening LangGraph: normalize -> blurb -> filter gate -> classify theme (or pinned theme) -> score match -> extract gaps
  -> SQLite (jobs, screenings, tracking, ground truth, cv drafts)
  -> FastAPI + Jinja2 + HTMX + Alpine.js dashboard: board (review queue, add by URL) / job detail / profile
  -> on demand, "Prepare CV": CV LangGraph (Sonnet drafts, Opus critiques)
       draft_cv --> critique_cv --(revise, attempts < 3)--> draft_cv
                         |
                  (approve, or 3 attempts)
                         v
       CVDraft version -> manual edit -> styled HTML -> headless Chrome -> A4 PDF
```

## Eval

`python evals/run_eval.py` re-screens every job in the ground-truth table and scores it; `--fast` scores existing screenings. With the example profile this runs on the six fictional seed jobs.

On the author's private set of 24 hand-labeled postings: **75% theme accuracy** and **85% match-level agreement within one grade**. Of the theme misses, half were jobs correctly removed by a filter rule before classification, not classifier errors.

## Roadmap: pipeline revamp (planned)

Not built yet. Design under review in [`docs/pipeline-revamp.md`](docs/pipeline-revamp.md): instead of screening against fixed themes and generating one CV per job, the pipeline learns *archetypes* (kinds of work) from postings marked as market data, and reuses one CV per archetype.

**Four layers instead of one per-job chain**

```mermaid
flowchart TB
    store["1 · Job store<br/>role card, skills, embedding,<br/>status, market-data switch"]
    market["2 · Market layer<br/>archetypes shared across lanes<br/>demand, strengths, gaps"]
    decide["3 · Decisions<br/>lane, eligibility<br/>fit x lane value x urgency"]
    cvlib["CV library<br/>one CV per archetype + lane slots"]
    letters["Cover letters<br/>one per job"]
    store --> market
    store --> decide
    market --> cvlib
    decide --> letters
    cvlib --> letters
```

**Assigning a new job to an existing archetype: embeddings first, LLM only when unsure**

```mermaid
flowchart LR
    card["Role card<br/>+ embedding + skills"] --> score["Score each archetype<br/>1. centroid similarity<br/>2. nearest neighbors<br/>3. skill overlap"]
    score --> gate{"clear<br/>winner?"}
    gate -- yes --> direct["Assign directly<br/>no tokens, instant"]
    gate -- "no / close / thin" --> llm["LLM judges top 3<br/>archetype or none,<br/>reason, confidence"]
```

**Reworking the archetypes (manual, on demand): two independent tracks, reconciled, then human review**

```mermaid
flowchart LR
    pool["Market-data jobs<br/>refresh outdated role cards"] --> t1["Track 1 · structure from data<br/>UMAP + HDBSCAN,<br/>keep stable clusters"]
    pool --> t2["Track 2 · LLM taxonomy<br/>propose, refine,<br/>label every job"]
    t1 --> rec["Reconcile<br/>final archetypes,<br/>merge / split / retire"]
    t2 --> rec
    rec --> check["Consistency check<br/>re-assign every job"]
    check --> review["Human review + confirm<br/>versioned set, CVs flagged outdated"]
```

## Build log

[`plan.md`](plan.md) records the phases, design decisions and the bugs found along the way.
