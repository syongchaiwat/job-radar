# Pipeline revamp: lanes, market data, archetypes, CV library

Status: **approved** (Oct 2026). Phases 1 (foundation) and 2 (archetypes) built; phases 3-5 pending. Progress is logged in `plan.md`.

## 1. Why

The current pipeline screens every job against five hand-written themes and generates a CV per job. Using it for real exposed four problems:

1. **CV per job is wasteful.** Jobs of the same kind need nearly the same CV, but every CV run costs ~90k tokens and a few minutes. 30 applications = ~2.7M tokens for mostly identical output.
2. **Themes are hand-written and static.** They were derived from 24 seed jobs in Aug 2026. Revising them means editing five files by hand, and nothing tells you when the market has shifted.
3. **Jobs differ in purpose and timing, not just content.** A working-student job, a thesis internship, a summer internship and a full-time role are applied to at different times, with different urgency and different criteria, and their postings range from one paragraph to two pages. The current pipeline treats them all the same.
4. **Archived jobs lose their value.** A posting you don't apply to still says something about the market (which tools keep appearing, which levels are asked for). Today that information is discarded with the job.

## 2. Current state (verified against the code)

- Screening graph (`src/pipeline/graph.py`): normalize → blurb → filter gate → classify theme (or forced theme) → score match → extract gaps. Themes are five vault files (`profile/themes/theme-*.md`) with hand-written strengths, gaps, low-hanging fruit, story angles and retrieval keywords.
- CV graph (`src/pipeline/cv_graph.py`): draft (Sonnet) ⇄ critique (Opus), up to 3 rounds, with deterministic guardrails (honesty quotes, skill groups 3-5, summary length, no grades). One `CVDraft` row per job and version.
- Tracking (`Tracking.status`): new / shortlist / applied / in-process / offer / rejected / ignored (shown as "Archived").
- Labels: `GroundTruth` (seed labels + `user_correction` from "Your labels"); `Job.forced_theme` pins a theme.
- DB today: 140 jobs (82 Adzuna, 24 seed, 34 manual), 26 CV drafts across 7 jobs.

## 3. Core concepts

### 3.1 Two independent switches per job

| Switch | Values | Meaning |
|---|---|---|
| **Application status** | new → shortlist → applied → in-process → offer / rejected, or **archived** | What you did with the job. Archived = didn't apply; no reason needed. |
| **Market data** | on / off | Whether this posting should shape the archetypes and market stats. Independent of status: a vague job you apply to can be off; a rich posting you archive can be on. |

### 3.2 Lanes: why and when

A lane captures the purpose and timing of an application: e.g. *working student / part-time*, *thesis internship*, *summer internship*, *full-time*. Lanes are defined in a profile config (`profile/lanes.md`), not hard-coded, so the set can change.

- Detected automatically from the role card's lane signals (title words like "Werkstudent"/"intern", duration, start date, workload), overridable with one click.
- Drive only the **application workflow**: eligibility rules, ranking ("lane value"), and the small lane-specific slots in CVs and cover letters.
**How lanes are specified.** One section per lane in `profile/lanes.md` (vault-edited, synced like the rest of the profile):

```markdown
## Working student / part-time
- Detect: titles with "Werkstudent", "working student", "student assistant", "part-time"; workload 10-50%
- Eligible: workload within the weekly hours cap during the semester; Zurich commute area
- Value: flexible hours, relevance to the master's topics, long-term option
- CV slot: "Available part-time during the semester"

## Thesis internship
- Detect: "Praktikum" / "internship" lasting ~6 months, or "master's thesis" in the posting
- Eligible: start date matches the thesis semester
- Value: can the internship host the thesis; supervisor fit
- CV slot: "Looking for a thesis collaboration from <semester>"
```

Detection uses the lane signals the role card already extracts (title words, duration, workload, start date) plus these hints; an LLM resolves ambiguous cases, and you can override. **Not needed until Phase 5**: Phases 1-4 only store the raw lane signals on each role card, so `lanes.md` can be written when lanes are built, and existing jobs get their lanes then without re-extraction.

- Do **not** split archetypes, market data or CV strength. There is no separate "learning lane": every job with market data on feeds the market layer, whatever its lane or status.

### 3.3 Archetypes: what kind of work

Archetypes replace the five static themes. They are **shared across all lanes** and learned from the jobs you mark as market data:

- Discovered and revised only when you trigger a rework on the Classify page (§5.3).
- Each has a generated definition, include/exclude criteria and defining skills, plus market stats.
- New jobs between reworks get a suggested archetype automatically (§5.2).
- Versioned: each confirmed set is `archetype_set` v1, v2, … so older assignments stay interpretable.

### 3.4 Role card and skill vector: what gets compared

Raw postings are bad comparison material (company blurbs, benefits, legal text, mixed languages). Every job is condensed at intake into:

- **Role card**: a short normalized summary in **English** (enforced by the schema and a language check): normalized title, core responsibilities, required skills, domain, level, languages, lane signals.
- **Skill vector**: the job's canonical skills (via the skill dictionary, §4), IDF-weighted so rare skills matter more than ubiquitous ones like Python. Precise and explainable ("matched on LangGraph, RAG, evals").

## 4. Data model changes

| Table / field | Purpose |
|---|---|
| `Job.lane`, `Job.lane_source` (auto/user) | Lane per job |
| `Job.market_data` (bool, default off) | The market-data switch |
| `RoleCard` (job_id, prompt_version, model, title_norm, responsibilities, domain, level, languages, lane_signals, created_at) | Structured extraction; `prompt_version` + `model` let a rework refresh only outdated cards |
| `Skill` (canonical name, category) and `SkillAlias` (alias → skill) | Skill dictionary ("LLMs", "large language models", "GenAI" → LLM). Grows as new aliases appear: the model proposes, you approve |
| `JobSkill` (job_id, skill_id, required/nice-to-have) | Queryable skills per job; re-mapped deterministically when aliases merge (no LLM) |
| `Embedding` (job_id, model, role_card_hash, vector) | Dense vector of the role card; recomputed only when the card or model changes |
| `ArchetypeSet` (version, created_at, notes) and `Archetype` (set_version, name, definition, include/exclude, defining_skills, status active/retired, maps_from) | Versioned archetypes |
| `JobArchetype` (job_id, archetype_id, role primary/secondary, score, method embedding/llm/user, confidence, rationale) | Assignments, including how each was made |
| `CVVersion` (archetype_id, markdown, market_snapshot_hash, profile_hash, verdict, scores, created_at) | CV library: one current CV per archetype |
| `Job.cv_version_id` | Which CV a job uses |
| `CoverLetter` (job_id, cv_version_id, markdown, verdict, scores, created_at) | One per job, versioned |

Existing `CVDraft` rows stay as legacy per-job CVs (still viewable). `GroundTruth`'s theme labels belong to the legacy theme set (v0).

## 5. Pipelines

### 5.1 Intake (per job)

1. Fetch / paste (unchanged).
2. **Extract role card** with Sonnet (~2-3 cents/job), English enforced; flag non-English output.
3. **Canonicalize skills** through the dictionary; unknown terms go to a "new aliases" review list.
4. **Embed** the role card (local model, milliseconds).
5. **Detect lane** from lane signals (overridable).
6. **Eligibility** by lane (from `lanes.md` + `filters.md`): workload limits, start date, location, language. Hand-added jobs only get warnings (existing behavior).
7. **Suggest archetype** (§5.2).
8. **Fit score** against the archetype's computed strengths and gaps (§5.4), replacing the prose theme profile.

### 5.2 Assigning one job to an existing archetype (frequent: fast and cheap)

1. **Score each archetype three ways**, then combine:
   - *Centroid similarity*: job embedding vs the mean of the archetype's member embeddings.
   - *Nearest neighbors*: mean similarity to the 5 most similar members (handles archetypes with sub-types).
   - *Skill overlap*: job skill vector vs the archetype's IDF-weighted skill profile.
2. **Decide**:
   - *Clear winner* (top score above threshold and clear margin over second): assign, no LLM call.
   - *Uncertain* (low score, close race, thin posting): LLM adjudication (Sonnet). Input: role card + top 3 archetypes, each with definition, include/exclude criteria and 2-3 example members. Output (structured): archetype or "none", rationale, confidence.
   - *Close second*: stored as secondary archetype; CVs use the primary.
3. **Calibrate** thresholds on your confirmations/corrections so the direct path is ≥ ~95% correct; everything less certain goes to the LLM.

Why hybrid: embeddings capture the topic but miss the nature of the role ("uses LLM tools" vs "builds LLM systems"); a pure LLM is inconsistent across runs, sensitive to option order, and spends tokens on obvious cases. Expected: ~70-80% assigned instantly for free, the rest in 1-3 s for a few thousand tokens.

### 5.3 Manual archetype rework (rare: quality over cost)

Runs on all jobs with market data on, triggered from the Classify page.

1. **Refresh only outdated role cards** (old `prompt_version`/model); re-map skills through the dictionary deterministically.
2. **Track 1: structure from the data.** UMAP to ~5-10 dimensions → HDBSCAN (chooses the number of clusters, labels misfits as outliers) → repeated across parameter settings and bootstrap samples; keep only clusters that reappear consistently (stability / consensus clustering). Single runs are unreliable at small sizes; stability is what makes the result trustworthy.
3. **Track 2: taxonomy by the LLM.** Independently, Opus reads role cards in batches, proposes a taxonomy, refines it batch by batch, then labels every job with the final version (TnT-LLM pattern). Better at semantic distinctions embeddings blur.
4. **Reconcile (Opus).** Inputs: both proposals, per-cluster stats (top skills with frequencies, titles, domains, sample role cards) and the current archetypes. Output: final archetypes (names, definitions, include/exclude criteria, defining skills), merges/splits/retirements, an old→new mapping for continuity, placement of outliers. Agreement between tracks = high confidence; disagreement = flagged for review.
5. **Consistency check.** Run §5.2 over every job with the final definitions; jobs whose assignment disagrees with their cluster go to the review list. This also proves the definitions work for future jobs.
6. **Human review** on the Classify page (§7.3): 2D map, archetype cards, diff vs current set, quality signals (stability, cohesion, outlier share, track agreement, change vs previous set). Rename / merge / split / move, then confirm.
7. **On confirm:** new `ArchetypeSet` version; assignments rewritten; generated archetype notes exported (§6); retired archetypes' CVs archived; affected CVs flagged outdated.

Below ~40 market-data jobs Track 1 is weak and Track 2 carries the result; the reconcile step weighs them and the page shows the job count.

### 5.4 Market layer (per archetype, lane-agnostic)

Computed deterministically from jobs with market data on:

- **Demand**: share of member jobs mentioning each canonical skill; level, language and domain distributions; last 6 months vs all time (trend).
- **Strengths**: demanded skills your `projects.md` evidence covers (set comparison through the skill dictionary against each project's `Tools:`).
- **Gaps**: demanded skills with no evidence, ranked by demand.
- **Suggestions** (optional, LLM on demand): next steps to close the top gaps; you keep your own to-do list alongside.

### 5.5 CV library (one CV per archetype)

- Built by the existing draft ⇄ critique loop, with the input changed from one posting to the **archetype's market brief** (definition + demand stats + top requirements across all members, every lane, archived included) plus your profile. The CV is the strongest proof of the archetype's skills; lanes never remove tools or projects.
- **Lane slots**: small parameterized parts (availability line, summary emphasis, e.g. "available part-time during the semester, open to a thesis collaboration") filled per job at export time, no regeneration.
- **Outdated badge** when the archetype's `market_snapshot_hash` or your `profile_hash` changed since the CV was built ("12 new market-data jobs", "projects.md changed").
- **Explicit trigger only**; never regenerates on its own. All existing guardrails stay.
- Manual edits and PDF export work as today, per CV version.

### 5.6 Cover letters (one per job)

- Inputs: role card + full description + the job's CV version + `projects.md` + lane slot.
- Draft (Sonnet) ⇄ light critique (1-2 rounds) reusing the honesty rules: every claim traceable to the CV or projects; company-specific motivation only from the posting text.
- Edit and PDF export like CVs.

### 5.7 Ranking (active applications)

`priority = fit × lane value × urgency`

- **Fit**: §5.1 step 8.
- **Lane value**: per-lane criteria from `lanes.md` (e.g. thesis internship: can it host the thesis; summer internship: conversion to full-time, sponsorship; student job: hours flexibility, commute).
- **Urgency**: application deadline / posting age.

## 6. Profile and vault changes

| Today | After |
|---|---|
| `profile/themes/theme-*.md` (hand-written) | Retired. Replaced by generated archetype notes in `job-system/generated/archetypes/` (definition, top skills with frequencies, strengths, gaps), overwritten on every confirmed rework and marked "generated". Written from the app into the vault in a separate folder; `sync_profile.py` never copies it back. |
| Theme strengths / gaps | Computed (§5.4) |
| Low-hanging fruit | Market page action list |
| Story angles | Dropped from theme files; per-project framing stays in `projects.md` |
| `Theme angles: T1..T4` in `projects.md` | Replaced by a free-text `Angles:` field. Today each project says e.g. `T2: flagship RAG story`, keyed to theme codes; once archetypes are renamed, merged or split, those keys point at nothing. Free text keeps your judgment without depending on archetype names, e.g. `Angles: strongest for LLM/agent roles (grounding guardrails); for finance roles, lead with evaluation rigor`. The CV drafter reads it next to the archetype's market brief. |
| Retrieval keywords | Generated from each archetype's top titles and skills (for API ingestion) |
| `constraints.md` target lanes | Move into `lanes.md` (definitions, detection hints, eligibility, value criteria, slot text) |
| `filters.md` | Stays (exclude/flag rules), lane-aware where needed |

Hand-written input lives in exactly two places: `projects.md` (evidence) and the Classify review (judgment).

## 7. Pages

1. **Board**: add jobs, application status, market-data toggle (bulk select), lane and archetype badges, filters (lane, status, market data, "no archetype yet"). Active-application view = filter (e.g. shortlisted student jobs), no separate batch concept.
2. **Job Detail**: lane (override), archetype with confidence and "why" (matched skills or LLM rationale), CV picker from the library (archetype preselected), cover letter generate / edit / PDF.
3. **Classify**: pool of market-data jobs with filters and counts, current archetypes, Run → proposal as a diff, quality signals, Confirm. Also lists outdated role cards and new skill aliases to approve. Review tools are separate actions, all applied to the draft proposal until you confirm:
   - **Members**: expand any archetype to see its jobs (title, company, lane, how assigned, confidence, whether both tracks agreed).
   - **Rename**: edit the name and definition inline.
   - **Merge**: tick two or more archetypes → Merge → choose the name; their jobs combine.
   - **Split**: open one archetype → the LLM proposes sub-groups (or you create a new one) → jobs are assigned to each part, adjustable.
   - **Move**: per job, a dropdown to move it to another archetype or to "none".
   - **Confirm as vN** stays a separate button that commits everything at once.
4. **Market**: per archetype demand, strengths, gaps, trend, suggestions and to-dos.
5. **CV Library**: one card per archetype (current CV, built date, linked jobs, outdated badge, Generate / Regenerate, edit, PDF).
6. **Profile**: as today.

## 8. Migration

1. Backfill role cards, skills and embeddings for the existing 140 jobs (~$3-4 with Sonnet, once).
2. `market_data` starts off for all jobs; you mark the ones worth keeping (bulk select).
3. **Archetype set v0** = the five current themes, so CV picking works before the first rework. Existing assignments come from current screenings and `forced_theme`.
4. **No real clustering run until you've gone through the existing 140 jobs** and flagged which ones count as market data. Until then, Phase 2 is tested only on the fictional example jobs in `examples/` and synthetic fixtures. First real rework once flagging is done and enough market-data jobs exist (target ≥ 40).
5. Existing per-job `CVDraft`s stay readable as legacy. The current per-job "Prepare CV" stays available until the CV library ships, so applications don't wait on the rebuild.
6. Eval: the theme-accuracy eval keeps working on set v0; a new eval measures §5.2 assignment accuracy against your confirmed archetype labels.

## 9. Phases

| # | Phase | Delivers | Done when |
|---|---|---|---|
| 1 | Foundation | Role cards, skill dictionary + alias review, JobSkill, embeddings, `market_data`, backfill | Every job has a role card, skills and an embedding; market-data toggle on the board |
| 2 | Classify | Archetype tables + versioning, set v0, §5.2 assignment, §5.3 rework, Classify page | Tested on example/synthetic jobs: a rework proposes, you edit and confirm, assignments update, notes exported. First real run only after you've flagged the existing jobs |
| 3 | Market | §5.4 stats, Market page | Each archetype shows demand, strengths, gaps, trend |
| 4 | CV library | `CVVersion`, market brief input, lane slots, outdated detection, CV Library page, picker on Job Detail | One CV per archetype reused across jobs; badge flips when market or profile changes |
| 5 | Applications | Lanes (`lanes.md`, detection, override), ranking, cover letter loop | A shortlisted job gets lane, priority, CV and cover letter without per-job CV runs |

## 10. Cost and time

| Item | Today | After |
|---|---|---|
| 30 applications | ~30 CV runs ≈ 2.7M tokens | ~4-6 CV runs + 30 cover letters ≈ 0.5M tokens |
| Intake per job | screening ≈ 14k tokens | role card (Sonnet) + embedding + LLM only for uncertain assignment |
| Archetype rework | manual file editing | minutes, roughly $1-3 per run |
| Backfill | — | once, ~$3-4 |

## 11. Risks and failure modes

- **Skill dictionary quality.** Bad aliasing makes demand stats noisy. Mitigation: proposals need your approval; deterministic re-mapping; stats show raw counts.
- **Small sample instability.** Clustering under ~40 jobs is unreliable. Mitigation: stability filtering, LLM track, job count shown.
- **Archetype churn.** Frequent reworks invalidate CVs and labels. Mitigation: versioned sets, old→new mapping, reworks only on demand.
- **Thin postings.** Few skills to match. Mitigation: LLM adjudication, one-click manual pick, lane defaults.
- **Generated vault notes vs one-way sync.** The app writes into the vault for the first time. Mitigation: dedicated `generated/` folder, never synced back, clearly marked.
- **Embedding model change.** Vectors from different models aren't comparable. Mitigation: model stored per vector; full re-embed on change (cheap, local).
- **CV quality regression.** A market-brief CV might fit individual jobs less tightly. Mitigation: lane slots, optional per-job tweak, existing critique and guardrails.

## 12. Decisions (from review, Oct 2026)

1. **Cover letters: English only.**
2. **Lanes:** working student / part-time, thesis internship, summer internship, full-time.
3. **Generated archetype notes** are exported to the vault in `job-system/generated/archetypes/`.
4. **Market data is off by default** for every job; you mark the ones worth keeping.
5. **API ingestion:** keep the clients and drive their keywords from the archetypes, but **no new automated ingestion for now**. Before turning it back on, evaluate the sources: posting quality, overlap with postings found elsewhere, and how many require German.
6. **No real clustering** until the existing 140 jobs have been flagged for market data (§8).

## 13. Technical choices

- Embeddings: `bge-large-en-v1.5` via sentence-transformers (local; role cards are English by construction). Vectors in SQLite, brute-force numpy similarity (fine below ~10k jobs).
- Clustering: `umap-learn`, `sklearn.cluster.HDBSCAN`; bootstrap stability in-house.
- LLMs: role cards and adjudication on Sonnet; taxonomy and reconcile on Opus; CV and cover-letter loops as today (Sonnet drafts, Opus critiques).
- New dependencies: `sentence-transformers`, `umap-learn`, `scikit-learn`.
