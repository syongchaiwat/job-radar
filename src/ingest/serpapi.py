"""SerpApi Google Jobs client (free tier: 250 searches/month).
https://serpapi.com/google-jobs-api

Two quirks confirmed by manual testing, not documented anywhere obvious:
1. Google's Jobs vertical returns zero results for Switzerland unless the
   search runs in German -- gl="ch" and hl="de" together. hl="en" (the
   natural default) silently returns 0 results for any Zurich/CH query,
   even though the exact same params work fine for US/UK locations. This
   also means most returned postings are German-language.
2. The engine does not support boolean OR queries reliably -- multi-word OR
   terms (e.g. "data scientist OR machine learning engineer") return 0
   results even though a short single-word OR ("data scientist OR
   engineer") works. Treat `q` as one plain phrase, not a keyword-OR list.

Because of (2) we can't do Adzuna's one-call-with-all-keywords-OR'd trick,
and the free tier (250/month) can't cover one call per keyword per group
per day either. Instead: one call per group per day, rotating through that
group's keyword list by day-of-year so every keyword gets tried eventually.
~6 groups x 1 call/day ~= 180 calls/month, well inside the free quota.
"""
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

from src.ingest.base import JobDict

SERPAPI_URL = "https://serpapi.com/search.json"

_RELATIVE_DE = re.compile(r"vor\s+(\d+)\s+(Stunde|Tag|Woche|Monat)")
_RELATIVE_UNIT_DAYS = {"Stunde": 1 / 24, "Tag": 1, "Woche": 7, "Monat": 30}


class SerpApiNotConfigured(Exception):
    pass


def fetch_group(
    group: str,
    keywords: list[str],
    location: str = "Zurich, Switzerland",
    results: int = 10,
) -> list[JobDict]:
    api_key = os.environ.get("SERPAPI_KEY")
    if not api_key:
        raise SerpApiNotConfigured("SERPAPI_KEY not set in environment")
    if not keywords:
        return []

    keyword = keywords[date.today().timetuple().tm_yday % len(keywords)]

    params = {
        "engine": "google_jobs",
        "q": keyword,
        "location": location,
        "gl": "ch",
        "hl": "de",
        "api_key": api_key,
    }
    resp = httpx.get(SERPAPI_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    jobs = []
    for r in data.get("jobs_results", [])[:results]:
        apply_options = r.get("apply_options") or []
        url = r.get("source_link") or (apply_options[0]["link"] if apply_options else None)
        detected = r.get("detected_extensions", {})
        jobs.append(
            {
                "source": "serpapi",
                "url": url,
                "company": r.get("company_name", "Unknown"),
                "title": r.get("title", ""),
                "description": r.get("description"),
                "location": r.get("location"),
                "level": detected.get("schedule_type"),
                "posted_at": _parse_relative_posted(detected.get("posted_at")),
                "search_hint": group,
            }
        )
    return jobs


def _parse_relative_posted(text: Optional[str]) -> Optional[datetime]:
    """Google gives German relative text ("vor 6 Tagen") not a real date."""
    if not text:
        return None
    m = _RELATIVE_DE.search(text)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return datetime.now(timezone.utc) - timedelta(days=n * _RELATIVE_UNIT_DAYS[unit])
