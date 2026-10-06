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

# "strong"/"good" get the accent (purple) badge treatment, "moderate"/"stretch" get muted gray -- matches the mockup's two-tier grouping
MATCH_STYLES = {
    "strong": "accent",
    "good": "accent",
    "moderate": "muted",
    "stretch": "muted",
}
