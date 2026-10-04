"""Archetypes (pipeline revamp, Phase 2): kinds of work learned from market-data jobs.

- features.py  pool loading, skill IDF vectors, compact role-card text
- assign.py    single-job assignment (embeddings + skill overlap, LLM when unsure)
- track1.py    stable clustering (UMAP + HDBSCAN over bootstrap runs)
- track2.py    LLM taxonomy (Opus, batch by batch) + labeling
- rework.py    orchestrates a rework into a draft proposal
- commit.py    set v0 seeding, confirming a proposal, vault note export
See docs/pipeline-revamp.md §5.2-5.3.
"""
