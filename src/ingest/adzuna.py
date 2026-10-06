"""Adzuna API client (free tier). https://developer.adzuna.com/

One call per search group using what_or (any-of-these-words) to stay well inside the
free-tier daily call quota instead of one call per keyword.
"""
import os
from datetime import datetime
from typing import Optional

import httpx

from src.ingest.base import JobDict

ADZUNA_BASE = "https://api.adzuna.com/v1/api/jobs/ch/search/1"


class AdzunaNotConfigured(Exception):
    pass


def fetch_group(
    group: str,
    keywords: list[str],
    where: str = "Zurich",
    max_days_old: int = 2,
    results: int = 20,
) -> list[JobDict]:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        raise AdzunaNotConfigured("ADZUNA_APP_ID / ADZUNA_APP_KEY not set in environment")

    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what_or": " ".join(keywords),
        "where": where,
        "max_days_old": max_days_old,
        "results_per_page": results,
        "content-type": "application/json",
    }
    resp = httpx.get(ADZUNA_BASE, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for r in data.get("results", []):
        jobs.append(
            {
                "source": "adzuna",
                "url": r.get("redirect_url"),
                "company": (r.get("company") or {}).get("display_name", "Unknown"),
                "title": r.get("title", ""),
                "description": r.get("description"),
                "location": (r.get("location") or {}).get("display_name"),
                "level": None,
                "posted_at": _parse_date(r.get("created")),
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
