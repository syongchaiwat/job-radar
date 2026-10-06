"""Shared contract for per-source job clients (adzuna, jsearch, serpapi).

These are plain functions, not classes -- there's no shared behavior to
inherit, only a shared shape, and `run.py` calls them as functions
(`SOURCES = [(name, fetch_fn), ...]`). This module exists so that shape has
one documented, type-checkable home instead of three copies of the same
docstring.
"""
from datetime import datetime
from typing import Optional, Protocol, TypedDict


class JobDict(TypedDict):
    """Return shape every fetch_group() implementation must produce.

    All keys are always present; several are Optional because the source
    may not give us that field for a given posting (e.g. SerpApi's `level`
    comes from a free-text schedule_type, Adzuna never provides one).
    """

    source: str  # "adzuna" | "jsearch" | "serpapi"
    url: Optional[str]  # dedupe key is sha1(url) -- rows with no url are dropped by the caller
    company: str  # "Unknown" if the source didn't give one
    title: str
    description: Optional[str]
    location: Optional[str]
    level: Optional[str]
    posted_at: Optional[datetime]
    search_hint: str  # echoes the search group (archetype slug) this call was made for


class FetchGroup(Protocol):
    """Signature every ingest source module exposes as `fetch_group`.

    One call per search group (an archetype), keywords combined (OR'd, or otherwise folded into a
    single query) rather than one call per keyword, to stay inside each
    source's free/paid quota -- see the module docstring of each
    implementation for the specific rate-limit reasoning.

    Implementations may add extra source-specific keyword args (e.g.
    `where`, `max_days_old`, `results`) with their own defaults; callers in
    `run.py` only ever pass `group` and `keywords` positionally.

    Raises a module-specific `*NotConfigured` exception (not a generic one)
    when its required API key/env var is missing, so `run.py` can catch
    `Exception` broadly and print a useful per-source skip message without
    one bad source aborting the whole ingest run.
    """

    def __call__(self, group: str, keywords: list[str]) -> list[JobDict]: ...
