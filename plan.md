# job-radar: Build Plan

**Living document.** Drafted on 12 Aug 2026 as the build plan, then kept as a build log: it evolves alongside the code that satisfies each phase.

**Status:** Phases 0-4 complete (21 Aug 2026). 106 jobs in the DB (24 seed + 82 live Adzuna), all screened. Dashboard is FastAPI + Jinja2 + HTMX + Alpine + Tailwind (rewritten from an initial Streamlit build the same day real design mockups arrived -- see Phase 4 below). Still running local via Ollama (`qwen3:8b`) since Anthropic billing isn't sorted -- see "LLM provider" note below. Next: Phase 5 (automation).

**Goal:** a daily pipeline that retrieves new Swiss job postings per theme, screens them against the candidate's filters, scores match and gaps against their profile, and shows everything on a dashboard. Doubles as a portfolio project for agentic AI / LLM engineering.

**Decisions made (12 Aug 2026):**
- Stack: FastAPI backend + Streamlit dashboard, all Python
- Agents: LangGraph + Claude API (Haiku for screening, Sonnet for gap analysis)
- Sources: Adzuna API (free) + JSearch via RapidAPI (paid, LinkedIn coverage) + manual URL paste
- Scheduling: GitHub Actions cron, results committed to the repo
- Profile source of truth: a private folder outside the repo (synced into the gitignored `profile/`, never edited there; `examples/` holds a fictional profile)

**LLM provider (added 15 Aug 2026):** running local via Ollama (`qwen3:8b`) for now, since the Anthropic API key isn't set up yet. `src/pipeline/llm_config.py` centralizes the provider choice (`LLM_PROVIDER=anthropic|ollama` in `.env`) so switching to hosted Claude later is a one-line config change, not a rewrite. On this machine (M4 MacBook Pro, 16GB unified memory) qwen3:8b takes ~4-5 min/job on the full 4-node path — quality on 3 test jobs was genuinely good (correct theme classification, specific grounded rationale, defensible gap lists) but the speed means a full daily run could take an hour or more. Revisit moving to Anthropic once the key is sorted, especially before Phase 5 automation.

---

## Architecture

```
GitHub Actions (daily, cron configurable)
  └─> ingest.py: pull Adzuna + JSearch per theme keywords ──> dedupe vs DB
        └─> LangGraph screening pipeline (per new job):
              1. normalize      (title, company, location, workload, description)
              2. filter gate    (LLM interprets profile/filters.md rules -> keep/exclude/flag + reason)
              3. classify theme (1 / 2 / 3a / 3b / 4 / none)
              4. score match    (vs theme file + constraints.md -> strong/good/moderate/stretch + rationale)
              5. extract gaps   (named gaps vs profile, e.g. "wants Kubernetes: not in profile")
        └─> write to SQLite, commit DB + run log to repo

Local:
  streamlit run app.py   -> dashboard (reads SQLite via FastAPI)
  FastAPI                -> CRUD for job status, notes, manual URL ingestion
```

## Repo structure

```
job-radar/
├── README.md
├── plan.md                     (this file)
├── requirements.txt
├── .github/workflows/daily.yml (cron, default 06:00 Europe/Zurich, configurable)
├── profile/                    (gitignored working copy, synced from PROFILE_SOURCE_DIR or examples/)
├── data/                       (seed-jobs.md synced copy, job_radar.db)
├── src/
│   ├── ingest/                 (adzuna.py, jsearch.py, manual.py, dedupe.py)
│   ├── pipeline/                (langgraph graph: nodes above, state schema)
│   ├── db.py                    (SQLite via SQLModel: Job, GroundTruth, Screening, Tracking)
│   └── api.py                   (FastAPI)
├── app/                         (Streamlit: 1_Board.py, 2_Job_Detail.py, 3_Profile.py)
├── evals/                       (labeled_jobs.jsonl from seed-jobs.md, run_eval.py, results/)
└── scripts/
    ├── sync_profile.py          (profile source -> repo copy)
    └── seed_db.py
```

## Data model (core fields)

- **Job**: id, source, url, company, title, description, location, level, posted_at, first_seen (hash id, dedupe on url)
- **GroundTruth**: job_id, theme_raw, theme_code, fit_raw (hand-labeled seed jobs, eval reference)
- **Screening**: job_id, decision (keep/exclude/flag), filter_reasons[], theme, match_level, match_rationale, gaps[], target_lane, model_used, tokens, latency_ms
- **Tracking**: job_id, status (new/shortlist/applied/in-process/offer/rejected/ignored), applied_at, notes

---

## Phases

### Phase 0: skeleton (half a day) — ✅ done 14 Aug 2026
Repo, requirements.txt, SQLite schema (`src/db.py`), profile sync script, seed DB from `seed-jobs.md`.
**Done when:** `python scripts/sync_profile.py` copies the profile and the 24 seed jobs are queryable in SQLite. — verified: 24 jobs, 24 ground-truth rows, theme distribution matches (1:4, 2:9, 3a:2, 3b:3, 4:5, none:1).

### Phase 1: ingestion (1-2 days) — 🚧 code done 14 Aug 2026, blocked on API keys
- Adzuna (`src/ingest/adzuna.py`): one call per theme using `what_or` (any-of-these-words) to stay inside the free-tier quota, `where=Zurich`, `max_days_old=2`. Needs `ADZUNA_APP_ID` / `ADZUNA_APP_KEY`.
- JSearch (`src/ingest/jsearch.py`, RapidAPI): one call per theme, keywords joined with OR, `date_posted=today`. Covers Google-for-Jobs including LinkedIn-posted roles. Needs `RAPIDAPI_KEY`.
- Manual (`src/ingest/manual.py` + `scripts/add_manual_job.py`): paste a URL and description by hand via CLI (dashboard form comes in Phase 4) — the deliberate ToS-safe replacement for scraping LinkedIn directly, since it has no public API and blocks unauthenticated fetches.
- Theme keywords load live from `profile/themes/*.md` (`src/ingest/theme_keywords.py`) — editing a theme file and re-syncing changes ingestion queries with no code change.
- Dedupe by URL hash (`src/ingest/dedupe.py`, shared with `seed_db.py`) before any LLM call, and before hitting the DB at all.
**Done when:** one command fetches today's postings for all themes into SQLite without duplicates. — **Adzuna verified live 14 Aug 2026**: 100 fetched, 82 new, 18 cross-theme duplicates correctly caught, across real companies (EY, ICBC, SNB, ITech Consult...) with fresh timestamps and correct theme_hint tagging. Manual path verified: correctly deduped against an existing seed URL, correctly added a new synthetic test entry (removed after testing). JSearch still needs a RapidAPI key; skips gracefully in the meantime.

### Phase 2: LangGraph screening pipeline (2-3 days, the heart) — ✅ done 15 Aug 2026
- One graph, five nodes as in the architecture sketch. State = Pydantic model (`src/pipeline/schemas.py`).
- Two cost-control branches beyond the original sketch: filter_gate→exclude skips straight to END, and classify_theme→none does too, since there's no point running the deep-role nodes on a job that's already thrown out. Both fired correctly in testing (Novartis excluded at filter_gate on title alone).
- "fast" role for filter_gate/classify_theme, "deep" role for score_match/extract_gaps, routed through `src/pipeline/llm_config.py` so the provider (Anthropic or local Ollama) is a one-line `.env` change, not a rewrite.
- Every node logs tokens + latency to the DB: this becomes the observability story, and turned out to double as the runtime-comparison data across providers.
- Prompts live in versioned files (`src/pipeline/prompts/`), not inline strings: eval-able and diffable.
**Done when:** `python -m src.pipeline.run --job-id X` produces a full Screening row for any seed job. — Verified on 3 seed jobs (EY, Novartis, MDPI) via local Ollama: theme classification correct on all 3, filter/gap reasoning specific and grounded rather than generic. Known limitation surfaced in testing: seed jobs only have title/company/location/level in the DB, not full descriptions (seed-jobs.md never captured them) — so filter/match quality on seed jobs is directionally informative only, not a full-fidelity test. Live Adzuna jobs have real descriptions and are a fairer test; worth doing before trusting eval results in Phase 3. `python -m src.pipeline.run --all` running on the remaining backlog.

### Phase 3: eval harness (1 day, do NOT skip: this is the showcase) — ✅ built 20 Aug 2026
- Ground truth: `GroundTruth` table (not just the 24 seed jobs forever -- `source`/`created_at` track provenance so a future Phase 4 dashboard correction lands generically, no eval-script changes needed).
- Metrics: theme classification accuracy, an honest "excluded with real theme" review list (explicitly not a bug count -- GroundTruth has no separate expected-decision label, so a job can legitimately belong to a real theme AND be correctly excluded by a filter rule; verified by hand that 2 of the first 3 flagged were correct exclusions, only 1 was an actual bug), match-level agreement (exact + within-one, only for jobs whose ground truth uses the canonical strong/good/moderate/stretch scale -- ~7 of 24 use a different "accessible/weak" axis and are skipped rather than force-mapped).
- `python evals/run_eval.py` defaults to a fresh re-screen of every GroundTruth job (not scoring whatever's in the DB) since these jobs aren't run often enough for the cost to matter, and stale rows can silently mix pipeline versions -- this happened for real on 18-19 Aug. `--fast` flag scores existing rows for iterating on the eval script itself.
- Add new hand-labeled jobs over time; the eval set grows with use.
**Done when:** a baseline eval result is committed and the README shows the numbers. — Baseline (20 Aug 2026, local qwen3:8b): theme accuracy 18/24 (75%), match-level exact 5/13 (38%), within-one 11/13 (85%). Manual review of the 6 theme misses: 3 are correct exclusions (not real failures), 1 confirmed bug (Artificialy -- years-threshold confusion), 1 defensible dual-fit call (Proton), 1 real hallucination (enshift -- claimed it "builds data pipelines" when the posting says the analyst just uses an existing platform). Also fixed in this pass: `theme_rationale` was computed by classify_theme but never persisted to the Screening table -- silently discarded on every run until now, which is what made the enshift/Proton review possible at all.

### Phase 4: dashboard (2-3 days) — ✅ built 21 Aug 2026, rewritten same day

First build was Streamlit (Board table + widget-based Job Detail + Profile), verified working. Then real card-based design mockups arrived (dark theme, pill/segmented controls, specific 2-column Job Detail layout) and it was clear Streamlit couldn't hit that level of visual control without CSS-injection hacks against its internal, unstable DOM -- and it has no native pill/segmented-control widget in the pinned 1.39.0 anyway. Rebuilt the same day on **FastAPI + Jinja2 + HTMX + Alpine.js + Tailwind (CDN, no build step)** instead. Backend (SQLModel schema, LangGraph pipeline, eval harness) was untouched by this -- only `app/` changed.

- **Board page** (`app/routes/board.py` + `templates/board.html`): server-rendered card grid (CSS Grid via Tailwind, reflows to 1 column on mobile -- verified), theme pills + search + excluded-toggle all client-side via Alpine (106 jobs is small enough to filter in-browser, no server round-trip). Cards are plain `<a href="/jobs/{id}">` links -- this fully replaced the old dataframe-row-click/session_state approach, which was flaky under automated testing; a real link click doesn't have that problem, so the "Open a job" fallback picker was dropped as no longer needed. Query layer (`app/services/jobs.py`) fixed a latent bug found while building it: `Screening.job_id` has no unique constraint by design (multiple runs per job are allowed), so a naive join would show duplicate/stale cards after any re-screen -- now picks the latest Screening per job explicitly.
- **Job Detail page** (`app/routes/job_detail.py` + `templates/job_detail.html`): full screening output with the mockup's dual human-label + pipeline-node-name section captions ("Theme · CLASSIFY_THEME" etc.), status/notes Tracking panel as an HTMX form (`POST /jobs/{id}/tracking`, swaps `#tracking-panel` in place -- verified Alpine correctly reinitializes on the swapped-in content), full raw description at the bottom.
- **Profile page** (`app/routes/profile.py` + `templates/profile.html`): direct port of the Streamlit version's logic, numbers matched exactly pre/post-port. Low-hanging-fruit expanders use native `<details>/<summary>` -- zero JS needed.
- **Two new LLM capabilities**, both scoped narrowly (existing 4 pipeline nodes' prompts/logic untouched, `profile/projects.md` deliberately left unwired):
  - **Card blurb** (`generate_blurb_node`, new node inserted between `normalize` and `filter_gate` so it runs unconditionally -- even excluded jobs get a blurb for the audit view): one-sentence job summary, eager, backfilled for the pre-existing 106 jobs via `scripts/backfill_blurbs.py`.
  - **Description breakdown** (`src/pipeline/breakdown.py`, deliberately *not* a graph node): fixed schema (About the Role / Key Responsibilities / Requirements & Skills / Nice to Have), lazy -- computed on first Job Detail view, cached on `Job.description_breakdown`. Runs on Adzuna's hard-truncated (exactly 500 char) snippets too, but flagged with a visible "partial" note in that case rather than pretending the breakdown is complete.
- Real bug found and fixed during the rewrite: the FastAPI app never called `load_dotenv()`, so `LLM_PROVIDER=ollama` never loaded and the app silently defaulted to Anthropic (no key configured, hard failure). Fixed in `app/main.py`, must run before any import touching `src.pipeline.llm_config` (which reads the env var at import time).
- Second bug found while hardening the launch config: `uvicorn --app-dir` fixes Python's module resolution but not the process's actual working directory, so `DATABASE_PATH=data/job_radar.db` (a relative path in `.env`) broke when the server was launched from an unexpected CWD. Fixed at the source in `src/db.py`: `get_engine()` now anchors relative paths to the repo root instead of trusting CWD.
- `app/dashboard.py`, `app/pages/1_Job_Detail.py`, `app/pages/2_Profile.py` deleted; `streamlit`/`pandas` dropped from requirements.txt (confirmed no other file imported either); `jinja2`/`python-multipart` added.
**Done when:** the daily flow is: open dashboard, triage new jobs, move cards. — Verified in-browser end to end, including mobile viewport (one real overflow bug found and fixed: the match badge on Job Detail overflowed off-screen on narrow viewports, header now stacks with `flex-col sm:flex-row`). `evals/run_eval.py --fast` re-run after all pipeline changes: identical results to the last baseline, confirming `screen_job()`'s new `blurb=` parameter didn't break anything.

**Triage rework — ✅ built 30 Sep 2026** (after a Lavish UI review): the daily flow shifted from "skim everything the APIs pull" to "hand-pick interesting postings and work them", so the board became a review queue.
- **Add a job from the board** (`POST /jobs/add`, `partials/_add_job.html`): same steps as `add_manual_job.py` + `run --job-id` (dedupe -> `url_fetch.fetch_and_extract` -> `create_manual_job`, now shared in `src/ingest/manual.py` -> `screen_job`), optional theme pins `forced_theme`. Blocked fetch re-renders the form with a paste-description box; a duplicate URL links to the existing job.
- **Review queue**: "needs review" = tracking status still `new`. Default sort puts those first, then newest. Sort (newest, best match, theme, status, CV verdict) and status filter (Active / Needs review / In progress / Archived / All) are client-side in Alpine; sorting reorders cards with CSS `order` on the grid, so no reload and no re-render. Cards show a CV verdict chip.
- **Archive reuses `ignored`**, relabeled "Archived" (no schema change). The 106 adzuna/seed jobs were bulk-archived once (DB backup `data/job_radar.db.bak-pre-bulk-archive`); seed jobs stay the eval ground truth, only tracking status changed.
- **Job Detail**: review bar (Archive / Shortlist, `POST /jobs/{id}/review`; Prepare CV stays separate so shortlisting never spends credits). "Your labels" (`POST /jobs/{id}/labels`) upserts `GroundTruth(source="user_correction")`; a theme that differs from the screening pins `forced_theme` and re-screens (~12s measured). Match labels are stored only, never override `score_match`. The CV moved to a full-width section below the screening decision, rendered client-side (marked + DOMPurify, source kept in an escaped `<textarea>` so a draft can't inject markup), with critique feedback, unresolved gaps and earlier versions in `<details>` toggles.
- **Eval**: jobs with a forced theme are excluded from theme accuracy (the classifier never ran for them); match/gap scoring still counts.
- **Models**: screening moved to Anthropic (Haiku 4.5 + Sonnet 5). CV critique moved to Opus 5.5 at effort `high` (`critique` role in `llm_config.py`, native structured outputs since Opus 5.5 rejects forced tool calls); drafting stays on Sonnet 5. First run: a test CV approved in 3 attempts, honesty 5 / relevance 4 (Sonnet-only run of the same job: relevance 3), ~130k tokens, ~2 min.
- Small fixes: "1 months ago" pluralization, gap-chip casing (`FastAPI` no longer becomes `Fastapi`), stale "ground-truth file" wording.
**Done when:** a job can go from URL to screened card to reviewed to CV without touching the CLI. — Verified in-browser: add (happy path, duplicate, blocked fetch), review, labels + re-screen, rendered CV with versions, mobile viewport with no horizontal scroll; `run_eval.py --fast` unchanged at 18/24.

**Manual jobs: rules warn, don't exclude — 30 Sep 2026.** Every "no theme" card on the board turned out to be a filter-gate exclusion (the graph stops before `classify_theme`), not a classifier "none". For hand-added jobs that trade-off is wrong, so `PipelineState.manual` (set from `job.source == "manual"`) makes `filter_gate_node` downgrade exclude -> flag, keeping the rule as the first reason. Bulk sources keep the short-circuit. Re-screened the two affected jobs: both now have theme + match. Plan from here: keep adding manual jobs and labeling disagreements, then re-cluster all manual jobs into a revised theme set (expect a theme/eval migration).

**Pipeline revamp — Phase 1 (foundation) — Oct 2026.** Design: [`docs/pipeline-revamp.md`](docs/pipeline-revamp.md). Built:
- `RoleCard`, `Skill`, `SkillAlias`, `JobSkill`, `Embedding` tables and `Job.market_data`; `init_db()` now applies added columns to existing databases (`_migrate`).
- `src/enrich/`: role-card extraction on Sonnet (English enforced, German-word check flags slips), skill canonicalization (alias → canonical name → new *pending* skill; the known-skills list is passed to the model so it reuses names), local `bge-large-en-v1.5` embeddings keyed by card hash + model. Each step skips work that's already current (`ROLE_CARD_PROMPT_VERSION`).
- `scripts/enrich_jobs.py --missing` backfill; jobs added from the board are enriched automatically.
- UI: market-data toggle on cards, job page and in bulk (Select jobs), market filter; collapsible role card on Job Detail; Skills page (approve, merge into alias, rename/recategorize).
- Hardening: role cards use native structured outputs (`method="json_schema"`): with tool calling, 2 of 140 long postings came back with the skills list as plain text. An unknown skill category coerces to "other"; `llm_call.call` raises a clear error when structured output fails validation instead of returning None; extraction retries once; an empty job title is filled from the role card.
- Backfill result: all 140 jobs have role cards and embeddings (33 rich, 22 partial, 83 thin, mostly the 500-character Adzuna snippets), none flagged non-English, 145 skills pending review.
- **Title rule removed:** no more filtering on title words (Senior, Lead, Staff…): the hard-coded `BANNED_TITLE_WORDS` check and the matching line in `filters.md` are gone. Seniority is judged from the requirements (e.g. "5+ years" flags) and in match scoring. It had also misfired on "Member of Technical Staff" (matched "staff"). Re-screened the 6 affected jobs; eval theme accuracy 18/24 → 19/24, match within-1 11/13 → 12/14.
- **Adzuna jobs deleted:** the 82 API jobs (all archived, 80 with thin role cards, no CVs/labels/notes) and 10 skills only they used. Backup: `data/job_radar.db.bak-pre-delete-adzuna`. 58 jobs remain (34 manual, 24 seed).
**Next:** flag the existing jobs as market data, review pending skills, then Phase 2 (archetypes, tested on example/synthetic jobs until the flagging is done).

**Pipeline revamp — Phase 2 (archetypes) — Oct 2026.** Built (`src/archetypes/`, Classify page):
- Tables `ArchetypeSet` (versioned, one active, `params` holds calibrated thresholds), `Archetype`, `JobArchetype` (primary/secondary, method embedding/llm/user/rework/legacy, score, confidence, rationale), `ClassifyRun` (background rework + draft proposal JSON).
- **Set v0** seeded from the five legacy themes (members from your labels, pinned themes, latest screening), so matching works before the first rework.
- **Single-job assignment** (§5.2): centroid + 5-nearest-neighbor + IDF skill overlap (0.4/0.3/0.3, leave-one-out for members); clear winners assigned directly, the rest adjudicated by Sonnet (structured output). Thresholds calibrated on known members for ≥95% precision (first run: abs 0.67, margin 0.03, 64% direct coverage). New jobs from the board are matched after enrichment; the job page shows archetype, method and reason, and lets you pin, clear or re-match.
- **Rework** (§5.3): Track 1 = 54 UMAP+HDBSCAN runs (parameter grid x 80% bootstrap) → co-association → average linkage, stability per cluster; Track 2 = Opus taxonomy refined batch by batch, then labels every job; Opus reconciles both with the current set (maps_from), assigns every job; leave-one-out consistency check flags mismatches; quality signals (stability, cohesion, track agreement, ARI), 2D UMAP map. Draft edits: rename, move, merge, split (2-means + Sonnet naming). Confirm → new set, outside-pool jobs assigned, notes exported to `<PROFILE_SOURCE_DIR>/generated/archetypes/`.
- Fix found on the way: Opus 5.5 had a 4,096-token output cap (langchain-anthropic doesn't know the model id), which truncated long outputs and also squeezed the CV critique's thinking; now `max_tokens=32000`.
- First real rework on 64 market-data jobs: 7 archetypes (ML engineering & MLOps 16, applied data science & forecasting 13, LLM & agentic engineering 12, business/product/people analytics 8, quant finance 6, data & backend engineering 5, AI/data consulting 4), tracks ARI 0.51, 14 flagged, ~80k tokens (~$1), ~3.5 min. Awaiting review on the Classify page.

**Pipeline revamp — Phase 3 (market layer) — Oct 2026.** Built (`src/market/`, Market page):
- **Profile evidence:** terms from `projects.md` Tools, the CV template's skills and completed coursework, mapped to the skill dictionary deterministically (alias, exact, parenthetical) then by Sonnet once per new term (cached in `ProfileTerm`). The mapping prompt allows umbrella evidence (LightGBM → Machine Learning; Google Cloud Platform → Cloud Computing) but not neighbours (TensorFlow ≠ PyTorch). First version without umbrella rules marked Machine Learning (91% of jobs) as a gap; fixed. You can drop any mapping with "not evidence" (kept across remaps).
- **Stats per archetype** (active set, market-data members): skill demand share (required vs nice-to-have, last 6 months vs all), profile coverage (demand-weighted), strengths/gaps at ≥15% demand, level/lane/language/domain mix.
- **Market page:** archetype tabs, demand bars marked strength/gap, gaps ranked, strengths with evidence, Sonnet next-step suggestions (cached, "add to to-dos"), per-archetype to-dos (keyed by slug), member list. Generated vault notes now include strengths, gaps and coverage ("Write archetype notes" button, also on every confirm).
- Current read (set v0): coverage 64-75%; recurring real gaps PyTorch, Docker/Kubernetes, Azure, R, Git, Power BI, dbt.

**Pipeline revamp — Phase 4 (CV library) — Oct 2026.** Built (`src/cvlib/`, CV library pages):
- `CVVersion` table (one versioned CV per archetype, keyed by slug so it survives archetype-set versions) and `Job.cv_version_id` (pin a CV per job; default = latest CV of the job's archetype).
- The existing draft ⇄ critique loop is reused unchanged (all guardrails apply), fed a **market brief** instead of one posting: definition, top-25 demanded skills with shares, responsibilities sampled from member role cards, level/lane/domain mix; framing = market strengths to lead with and gaps never to claim; a target note tells both nodes it's an archetype, not a company.
- **Outdated badge:** source job ids + a market hash and a profile hash (projects, coursework, CV template) stored per version; the library flags new/removed market-data jobs, demand changes, or profile edits. Regenerate is explicit only.
- **Lane slots:** a one-line sentence appended to the summary at PDF time per job (defaults per employment type until `lanes.md`, Phase 5).
- Pages: CV library (cards per archetype, background generation with progress), per-archetype CV page (rendered CV, scores, critique, gaps, versions, edit, PDF), job page CV panel (which CV, lane line, PDF, preview, pick another CV). The per-job CV flow stays available under "Tailor a CV for this job only".
- First archetype CV (LLM & agentic AI): approved in round 2, honesty 5, relevance 4, ~92k tokens, 1.5 min; refused to claim Azure, Kubernetes, PyTorch, LangChain, Hugging Face, Linux.

**Pipeline revamp — Phase 5 (applications) — Oct 2026.** Built (`src/lanes.py`, `src/letters.py`):
- **`profile/lanes.md`** (vault): per lane `Key`, `Detect`, `Eligible`, `Value`, `CV slot`; the example profile has a fictional one. The CV library's lane sentence now comes from it.
- **Lane detection:** deterministic rules from role-card signals (67 of 82 jobs), Sonnet for ambiguous ones (e.g. 6-month internships without a thesis mention); overridable on the job page (re-assesses).
- **Lane assessment** (Sonnet, `LaneAssessment`): eligibility yes/no/unclear with reasons, lane value 0-1 with reasons, application deadline when stated; re-run when `lanes.md` changes (`scripts/assess_lanes.py --missing`) and on intake.
- **Ranking:** priority = fit × (0.3 + 0.7 × lane value) × urgency, ×0.3 if not eligible. Fit = share of the job's skills proven by the profile (required 1, nice 0.5); urgency from the deadline (or posting age). Board: lane filter, priority sort, lane/eligibility chips; job page: Lane & priority panel with editable deadline.
- **Cover letters** (`CoverLetter`): Sonnet draft ⇄ critique (≤2 rounds), English, grounded in the job's CV (library CV with lane sentence, else the per-job CV) + project database; honesty/relevance/specificity/tone, fabrication quotes must exist in the letter, word count 180-380, no grades, must name the company. Edit, regenerate, one-page PDF with the CV header (`cv_pdf.letter_to_pdf`). A first letter took ~73k tokens and ~1 min.
- **Timeline-first lanes:** internships ≤4 months or starting in summer ("13 weeks", "Summer 2027", May-August start) are summer internships; a guard overrules an LLM "working student" for a full-time internship ≤6 months.
- **Folders by component:** `src/pipeline/` split up; every component is a package with its own `prompts/` folder (`screening`, `cv` incl. the former `cvlib`, `letters`, `lanes`, `archetypes`, `enrich` incl. breakdown, `market`, `ingest`), shared LLM plumbing in `src/llm/` (call, config, schemas), profile loaders in `src/profile/`. Prompt files lost their component prefix (`archetype_merge.md` -> `archetypes/prompts/merge.md`); `load_prompt("component/name")`. Commands: `python -m src.screening.run`, `python -m src.cv.run`.
- **Legacy themes fully retired:** no theme code, files or columns remain. Screening is now 5 nodes (no classify step); match and gaps are judged against CV facts (education, skills, languages from the template) + the project database (CV-only hints stripped) + coursework, with the job's archetype as context. Enrichment and archetype assignment now run before screening on intake. Per-job CVs are framed by the job's archetype (market framing), `CVDraft.archetype_slug`. API ingestion searches by the most common job titles per archetype (`src/ingest/search_keywords.py`). Eval drops theme accuracy (keeps match-level agreement and an "excluded despite a fit label" review list); seed tables lose the Theme column. Removed: `classify_theme`, `forced_theme`/theme pins, the unused labels panel, `seed_v0` and set v0, `target_lane` (lanes cover it). `projects.md` "Theme angles (T1-T4)" became "Role angles" with plain labels. Theme files archived in the vault (`job-system/archive/legacy-themes/`). Screening cost rose from ~11k to ~32k tokens per job (full profile instead of a compact theme file). Eval after the change: match within one grade 12/15 (80%, was 12/14), exact 7/15 (47%, was 6/14); more jobs flagged by the filter gate (Haiku), mostly years-of-experience and location rules.
- **Profile page retired:** the graduation / permit countdowns moved to the top of Market; the legacy themes' hand-written "low-hanging fruit" were imported once as Market to-dos under the matching archetype; theme counts and keyword gaps are superseded by Market.
- **Classify map:** UMAP layout saved to `data/classify_layout.json`; reruns only when the job list or archetype set changes (or via *Recompute map layout*); UMAP calls serialized (`UMAP_LOCK`) after a Numba crash.
- Fixes on the way: grade check matched "within one grade" (eval wording); letter PDF first rendered everything as the header (CV parser), now a dedicated letter renderer.

### Phase 5: automation (half a day)
- GitHub Actions: cron 06:00 Europe/Zurich (cron is UTC: `0 4 * * *` summer / `0 5 * * *` winter, or just pick one), runs ingest + pipeline, commits SQLite + log.
- Secrets: ANTHROPIC_API_KEY, ADZUNA_APP_ID/KEY, RAPIDAPI_KEY.
- Failure -> GitHub issue auto-opened (actions have a setting for this) so silent breakage is visible.
**Done when:** two consecutive mornings produce fresh screened jobs with no manual step.

### Phase 6: polish for portfolio (ongoing)
- README: architecture diagram, eval table, cost per day, screenshots.
- Portfolio site: add as a project with a methodology article on the eval harness (Sunrise/Artificialy/Lobby all weight evals).
- Nice-to-haves later: weekly digest email, cover-letter drafter reading `profile/projects.md` story angles.

**CV draft/critique agent loop — ✅ built 23 Sep 2026** (the "CV-bullet suggester" nice-to-have above, grown into a real feature): a "Prepare CV" button on Job Detail runs a *second*, separate LangGraph -- `draft_cv → critique_cv`, looping back to `draft_cv` on a "revise" verdict, terminating on "approve" or a `MAX_ATTEMPTS=3` guardrail (`src/pipeline/cv_graph.py`). Unlike the screening graph, this one has an actual cycle, not just forward short-circuits -- confirmed LangGraph 1.2.11 supports a conditional edge back to an already-visited node natively, no workaround needed.

- **Ground truth, not the screening profile**: a new `cv_profile/themes/*.md` per theme (full education/work-experience/projects/skills/languages, not the strengths/gaps fragments in `profile/`), loaded via `src/pipeline/cv_profile_context.py`. Lives outside `profile/` on purpose -- `scripts/sync_profile.py` does a destructive `rmtree`+`copytree` of `profile/` from the profile source on every run, which would silently delete anything new placed inside it. Only `theme-2-agentic-ai-llm.md` was real (ported from a reviewed CV); the other 4 are marked placeholders (same facts, generic framing) with a visible warning banner, not yet trusted for a real application.
- **No mid-run interactive Q&A** (deliberately ruled out -- adds a pause/resume mechanism this app has never needed, LangGraph's `interrupt()`/checkpointer would work but wasn't worth the new surface area for a first version). Instead the critique's `unresolved_gaps` (e.g. "job wants Tableau: not found in profile") surface directly on the finished output for the user to fix the ground-truth file by hand, then click **Regenerate**, which seeds the next run with the previous draft + previous feedback (`CVDraft` table, `job_id` not unique -- mirrors `Screening`'s history-preserving shape, not `Tracking`'s single-row shape).
- **Real finding from testing, not just a theoretical risk**: drafting and critiquing share the same "deep" model (Sonnet-tier reasoning, same rationale as `score_match`/`extract_gaps`), and the first end-to-end test caught the self-critique leniency this predicts -- a corrupted postal code and an invented "Hugging Face" skill both got a `honesty_score` of 4/5 and nearly slipped through. Fixed by rewriting `critique_cv.md` to force an explicit line-by-line fact-check (every tool/skill/number/name cross-checked against the ground truth) before scoring, plus a deterministic backstop in `critique_cv_node` that overrides a stated "approve" if `honesty_score`/`relevance_score` are below 4. Re-tested: honesty scoring got visibly stricter (caught a fabricated project name and invented tools on the next run), but did **not** reach zero fabrication within 3 attempts on a deliberately LLM/RAG-heavy job posting (a misspelled name and a corrupted phone number persisted through all 3 revisions). This is why the design never auto-trusts output: the attempt ceiling is a real, visible "revise/maxed out" state on the UI, not a silent pass, and a human read-through before ever sending a generated CV stays required, by design not by accident.
- Exports to `cv_drafts/<job_id>_<company>-<title>_v<n>.md`, versioned so Regenerate never overwrites a prior attempt. Both `cv_profile/` and `cv_drafts/` are gitignored (they contain the candidate's contact details); since Oct 2026 the DB, profile and seed/eval data are gitignored too, so no personal data is ever committed.
**Done when:** clicking "Prepare CV" on a themed job produces a grounded, critiqued draft with a visible verdict, and Regenerate measurably responds to prior feedback. — Verified via `python -m src.pipeline.cv_run --job-id X [--regenerate]` (fresh run, regenerate run, and a deliberate guardrail stress-test against a placeholder-theme job, all terminating cleanly with real non-zero token/latency observability) and in-browser (button → panel states, mobile viewport for the score-pill row, `evals/run_eval.py --fast` re-run afterward confirming the schema additions didn't touch the screening pipeline: identical 18/24 baseline).

---

## Cost estimate
~20-50 new jobs/day after dedupe. Haiku screening ~1k tokens each, Sonnet deep pass only on kept jobs (~30%). Well under CHF 10/month at current API prices. JSearch cheapest tier ~USD 10-25/month: the only real recurring cost.

## Risks and notes
- LinkedIn has no public API and scraping violates ToS: JSearch + manual paste is the compromise. Manual paste-parse must be first-class, not an afterthought.
- Adzuna CH coverage is decent but not complete; treat sources as additive.
- Keep the private profile folder as source of truth. The sync script is one-way (source -> repo). Edit `profile/` and `data/seed-jobs.md` only at the source; edit this plan only here.
- Timebox: Phases 0-5 are roughly 7-10 focused days. Working end-to-end beats polished: get Phase 5 running, then iterate prompts against the eval set.

## Build order (strict)
0 -> 1 -> 2 -> 3 -> 5 -> 4 -> 6. Automation (5) before dashboard (4): a cron job filling SQLite is already useful via any DB viewer, while a dashboard without daily data is not.
