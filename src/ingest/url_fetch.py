"""Best-effort auto-fetch for manual job adds: given just a URL, try to pull
the title/company/location/description automatically instead of making the
user copy-paste the description by hand every time.

Deliberately gives up rather than working around a site that says no:
- LinkedIn has no public API and blocks unauthenticated scraping (this is
  documented already -- see manual.py) -- skipped without even trying.
- Several Swiss job boards (confirmed: jobagent.ch) sit behind DataDome,
  which answers with a JS/fingerprint challenge instead of the page. That's
  bot-detection, and defeating bot-detection isn't something this tool will
  do, technically feasible or not -- fetch_and_extract() just detects the
  challenge and returns None so the caller falls back to asking the user to
  paste the description themselves. No headless-browser workaround, no
  retries with different fingerprints.
- Uses a plain, honest User-Agent that identifies this as a script, not a
  spoofed browser -- confirmed by testing that this doesn't actually change
  the outcome on sites that *do* allow a normal fetch (e.g. company career
  pages on standard ATS platforms), so there's no reason to pretend to be
  something we're not.

Whatever text does come back is noisy (nav menus, cookie banners, "similar
jobs" lists mixed in with the real posting), so it's handed to the same
kind of LLM extraction step normalize_node uses, just with a wider prompt
that also pulls out location and cleans up the description itself.
"""
import re
from typing import Optional

import httpx

from src.pipeline.llm_call import call, load_prompt, truncate
from src.pipeline.schemas import ExtractedJobPosting

USER_AGENT = "job-radar/1.0 (+https://github.com/syongchaiwat/job-radar)"

BLOCKED_DOMAINS = ["linkedin.com"]

_BOT_CHALLENGE_MARKERS = [
    "please enable js",
    "just a moment",
    "captcha-delivery.com",
    "checking your browser",
    "cf-mitigated",
]


class FetchBlocked(Exception):
    """Raised (and caught internally) when a site can't or won't be fetched.
    Never used to justify trying harder -- only to explain why we stopped."""


def fetch_and_extract(url: str) -> Optional[dict]:
    """Returns {title, company, location, description} or None if the page
    couldn't be fetched -- blocked domain, bot-detection challenge, HTTP
    error, timeout, or a page with no job posting in it. Callers should fall back to a manually-pasted
    description when this returns None."""
    try:
        html = _fetch_html(url)
        page_text = _html_to_text(html)
        if len(page_text) < 200:
            return None  # too little text to be a real posting page
    except FetchBlocked:
        return None

    prompt = load_prompt("extract_job_posting").format(page_text=truncate(page_text, n=12000))
    parsed, _log = call("fast", prompt, ExtractedJobPosting)
    # A page can load fine and still hold no posting: jobs.ch "job-recommendations"
    # links return a shell (nav + footer) and load the job via JavaScript. Treat
    # that like a blocked fetch so the caller asks for a pasted description,
    # instead of saving menu text as the job and screening it.
    if not parsed.title or len(parsed.description) < 200:
        return None
    return {
        "title": parsed.title,
        "company": parsed.company or None,
        "location": parsed.location or None,
        "description": parsed.description,
    }


def _fetch_html(url: str) -> str:
    if any(domain in url.lower() for domain in BLOCKED_DOMAINS):
        raise FetchBlocked(f"{url} is on a known-blocked domain, not attempting")

    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=20,
            follow_redirects=True,
        )
    except httpx.HTTPError as e:
        raise FetchBlocked(f"request failed: {e}") from e

    if resp.status_code in (401, 403, 429, 503):
        raise FetchBlocked(f"got {resp.status_code}, likely bot-protected")

    if resp.headers.get("x-datadome") or resp.headers.get("cf-mitigated"):
        raise FetchBlocked("bot-detection header present")

    lower_body = resp.text[:2000].lower()
    if any(marker in lower_body for marker in _BOT_CHALLENGE_MARKERS):
        raise FetchBlocked("bot-detection challenge page detected")

    resp.raise_for_status()
    return resp.text


def _html_to_text(html: str) -> str:
    html = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text
