"""JSearch client (RapidAPI, paid). Wraps Google-for-Jobs, which aggregates
LinkedIn-posted roles among others -- this is the LinkedIn-coverage source
since LinkedIn itself has no public API and blocks unauthenticated scraping.

One call per search group, keywords joined with OR, to stay inside the paid quota.
"""
import os
from datetime import datetime
from typing import Optional

import httpx

from src.ingest.base import JobDict

JSEARCH_URL = "https://jsearch.p.rapidapi.com/search"


class JSearchNotConfigured(Exception):
    pass


def fetch_group(
    group: str,
    keywords: list[str],
    location: str = "Zurich, Switzerland",
    date_posted: str = "today",
    results_wanted: int = 20,
) -> list[JobDict]:
    api_key = os.environ.get("RAPIDAPI_KEY")
    if not api_key:
        raise JSearchNotConfigured("RAPIDAPI_KEY not set in environment")

    query = f"{' OR '.join(keywords)} in {location}"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    params = {"query": query, "date_posted": date_posted, "num_pages": 1}
    resp = httpx.get(JSEARCH_URL, headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for r in data.get("data", [])[:results_wanted]:
        jobs.append(
            {
                "source": "jsearch",
                "url": r.get("job_apply_link") or r.get("job_google_link"),
                "company": r.get("employer_name", "Unknown"),
                "title": r.get("job_title", ""),
                "description": r.get("job_description"),
                "location": r.get("job_city") or r.get("job_country"),
                "level": None,
                "posted_at": _parse_date(r.get("job_posted_at_datetime_utc")),
                "search_hint": group,
            }
        )
    return jobs


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
