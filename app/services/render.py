"""Presentation-layer helpers: pure functions, no DB access."""
import json
from datetime import datetime, timezone


def relative_time(dt: datetime | None) -> str:
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    seconds = (datetime.now(timezone.utc) - dt).total_seconds()
    if seconds < 60:
        return "just now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)} min ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    if days < 2:
        return "1 day ago"
    if days < 30:
        return f"{int(days)} days ago"
    months = int(days / 30)
    return "1 month ago" if months == 1 else f"{months} months ago"


def subtitle_line(job) -> str:
    """Joins whatever of location/level/relative-time/source is actually
    present -- no fabricated segments like "Remote-friendly" (nothing in
    the data backs that)."""
    parts = []
    if job.location:
        parts.append(job.location)
    if job.level:
        parts.append(job.level)
    parts.append(relative_time(job.first_seen))
    if job.source:
        parts.append(f"via {job.source.capitalize()}")
    return " · ".join(parts)


def gap_label(gap_text: str) -> str:
    """Heuristic short label for a gap's category badge -- presentation
    only, not a new LLM field. Strips a 'wants '/'Wants ' prefix, takes the
    text before the first ':', caps to ~4 words, dropping whole words (not
    a mid-word character cut) until it fits ~28 chars."""
    text = gap_text.strip()
    for prefix in ("wants ", "Wants "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    text = text.split(":")[0].strip()
    words = text.split()[:4]
    while words and len(" ".join(words)) > 28:
        words.pop()
    text = " ".join(words)
    # Upper-case only the first letter: str.capitalize() would turn "FastAPI" into "Fastapi".
    return text[0].upper() + text[1:] if text else "Gap"


def markdown_bullets_to_list(text: str | None) -> list[str]:
    """Lightweight bullet-list extraction for the Profile page's
    low-hanging-fruit sections -- avoids pulling in a full markdown library
    for content that's consistently simple '- item' bullet lists."""
    if not text:
        return []
    return [line.strip()[2:].strip() for line in text.splitlines() if line.strip().startswith("- ")]


def from_json_filter(raw: str | None):
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
