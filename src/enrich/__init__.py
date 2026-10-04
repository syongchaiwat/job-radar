"""Job enrichment (pipeline revamp, Phase 1): role card -> skills -> embedding.

Everything downstream (archetype assignment, clustering, market stats) compares
these normalized representations instead of raw posting text. See
docs/pipeline-revamp.md §3.4 and §5.1.
"""
from src.enrich.enrich import enrich_job  # noqa: F401
