"""Shared display constants for the dashboard app."""

STATUS_OPTIONS = ["new", "shortlist", "applied", "in-process", "offer", "rejected", "ignored"]

STATUS_LABELS = {
    "new": "New",
    "shortlist": "Shortlist",
    "applied": "Applied",
    "in-process": "In process",
    "offer": "Offer",
    "rejected": "Rejected",
    "ignored": "Archived",  # D2: "ignored" is reused as the review queue's Archive action
}

# Board status filter groups. "Needs review" = never looked at (status still "new").
IN_PROGRESS_STATUSES = ["shortlist", "applied", "in-process", "offer"]
ARCHIVED_STATUSES = ["ignored", "rejected"]

MATCH_LEVELS = ["strong", "good", "moderate", "stretch"]

THEME_LABELS = {
    "1": "1 · Quant/Risk",
    "2": "2 · Agentic AI",
    "3a": "3a · Core ML",
    "3b": "3b · Data/Infra",
    "4": "4 · Business",
}

THEME_NAMES = {
    "1": "Quant Finance / Risk",
    "2": "Agentic AI / LLM",
    "3a": "Core ML Engineering",
    "3b": "Data / Backend Infra",
    "4": "Business / Consulting Analyst",
}

# "strong"/"good" get the accent (purple) badge treatment, "moderate"/"stretch" get muted gray -- matches the mockup's two-tier grouping
MATCH_STYLES = {
    "strong": "accent",
    "good": "accent",
    "moderate": "muted",
    "stretch": "muted",
}
