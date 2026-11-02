"""Shared display constants for the dashboard app."""

from src.tracking.core import STAGES, STATUS_LABELS  # noqa: F401  (status keys and labels live with the stage rules)

STATUS_OPTIONS = ["new", *STAGES]
TRIAGE_STATUSES = ["new", *(k for k, s in STAGES.items() if s.group == "triage")]
PROCESS_STATUSES = [k for k, s in STAGES.items() if s.group == "process"]
OUTCOME_STATUSES = [k for k, s in STAGES.items() if s.group == "outcome"]

MATCH_LEVELS = ["strong", "good", "moderate", "stretch"]

# "strong"/"good" get the accent (purple) badge treatment, "moderate"/"stretch" get muted gray -- matches the mockup's two-tier grouping
MATCH_STYLES = {
    "strong": "accent",
    "good": "accent",
    "moderate": "muted",
    "stretch": "muted",
}
