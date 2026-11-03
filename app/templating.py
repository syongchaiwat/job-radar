"""Jinja2Templates instance + custom filters, in its own module to avoid
circular imports between routes/ and services/."""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.constants import STATUS_LABELS
from src.tracking.core import FORMATS, INTERVIEW_KINDS, KIND_LABELS, OUTREACH_LABELS
from app.services import render as render_service

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

templates.env.filters["relative_time"] = render_service.relative_time
templates.env.filters["subtitle_line"] = render_service.subtitle_line
templates.env.filters["gap_label"] = render_service.gap_label
templates.env.filters["from_json"] = render_service.from_json_filter
templates.env.filters["status_label"] = lambda s: STATUS_LABELS.get(s, s)


def _event_day(iso: str | None) -> str:
    """'2026-10-28' -> 'Wed 28 Oct 2026' (event dates on the job page)."""
    from datetime import date

    try:
        return date.fromisoformat(iso).strftime("%a %-d %b %Y")
    except (TypeError, ValueError):
        return iso or ""


templates.env.filters["event_day"] = _event_day

STATIC_DIR = Path(__file__).resolve().parent / "static"


def static_url(path: str) -> str:
    """/static/<path>?v=<mtime>: browsers refetch a script as soon as it changes."""
    f = STATIC_DIR / path
    return f"/static/{path}?v={int(f.stat().st_mtime) if f.exists() else 0}"


templates.env.globals["static_url"] = static_url
templates.env.globals.update(status_labels=STATUS_LABELS, outreach_labels=OUTREACH_LABELS, kind_labels=KIND_LABELS, interview_kinds=INTERVIEW_KINDS, formats=FORMATS)
