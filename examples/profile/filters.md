---
name: filters
description: Plain-text filter rules interpreted by the screening agent. Edit freely, one rule per bullet.
---

# Screening Filters

The screening agent reads these as natural-language rules. "Exclude" removes the job before scoring (bulk-ingested jobs only; hand-added jobs get a warning instead). "Flag" keeps it but marks the concern.

## Exclude
- Jobs requiring fluent or native German (e.g. "verhandlungssicher", "fliessend Deutsch", "German C1/C2 required"). German as a plus is fine.
- Jobs requiring 8+ years of experience.
- Pure sales, recruiting, or marketing roles even if they mention AI.

## Flag (keep, but highlight)
- Onsite-only roles outside the Zurich commute area.
- Jobs requiring 5 or more years of experience (stretch, not impossible).
- Jobs where French or Italian is required.
- Full-time roles starting before the candidate graduates (only viable if convertible to part-time).

## Notes for the matcher
- "2-3 years experience" requirements are a match: the candidate has 4 years of industry experience.
- Internships, working-student roles, and thesis collaborations are always in scope regardless of the experience filter.
