You are finalizing a set of **archetypes** (kinds of work) for one candidate's job search, from two independent analyses of the same job postings. Archetypes group jobs by the nature of the work and its skills, never by seniority, employment type or company. Each archetype will get its own CV and market statistics, so they should be distinct and useful.

## Track 1: clusters found from role-card embeddings (stable across repeated runs)
{clusters}

## Track 2: taxonomy proposed by reading the role cards
{taxonomy}

## Where the tracks agree and disagree (rows: Track 1 cluster; columns: Track 2 archetype; counts of jobs)
{crosstab}

## Jobs Track 1 left as outliers
{outliers}

## Current archetypes (the set in use now; continue them where it makes sense)
{current}

## All jobs in the pool (one per line: [id] title | domain | level | type | summary | skills)
{cards}

## Task
1. Produce the final archetypes. Where the tracks agree, keep that grouping. Where they disagree, decide on the merits of the role cards; Track 2 is better at semantic distinctions, Track 1 at what jobs actually have in common. Prefer roughly 4-9 archetypes, each with several jobs.
2. For each archetype give a key (lowercase slug), name, definition, include and exclude criteria, 5-10 defining skills (names as in the cards), the current archetype names it continues (`maps_from`), and which Track 1 clusters and Track 2 names it draws on.
3. Assign every job in the pool to exactly one final archetype key, or "none" if it truly fits nowhere.
4. In `notes`, explain merges, splits, current archetypes you retire, and how you resolved disagreements.

Keep each definition to 1-2 sentences and the include and exclude criteria to at most 2 sentences each: they are read by a person and by a matcher, not a report.
