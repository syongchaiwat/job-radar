---
name: lanes
description: Application lanes for the example candidate. Read by job-radar for lane detection, eligibility, ranking and the CV/cover-letter lane sentence.
---

# Lanes

Each lane: `Key`, `Detect` (signals in a posting), `Eligible` (hard requirements), `Value` (what makes a job in this lane worth more), `CV slot` (one sentence added to the CV summary; empty = none).

## Working student / part-time
- **Key:** working-student
- **Detect:** "working student", "Werkstudent", "part-time", workload 10-50%.
- **Eligible:** At most 40% during the semester; Zurich area or remote in Switzerland.
- **Value:** Flexible hours; relevant ML/data work; could lead to a thesis or an offer.
- **CV slot:** Available part-time during the semester.

## Thesis internship
- **Key:** thesis-internship
- **Detect:** About 6-month internship mentioning a master's thesis, or a thesis offered by the company.
- **Eligible:** Starts in the final semester.
- **Value:** Can host the thesis; strong ML topic.
- **CV slot:** Looking for an industry master's thesis collaboration.

## Summer internship
- **Key:** summer-internship
- **Detect:** Summer internship, 2-4 months between June and September.
- **Eligible:** Summer after the final semester.
- **Value:** Converts to a full-time offer.
- **CV slot:** Available for a summer internship.

## Full-time
- **Key:** full-time
- **Detect:** Permanent or full-time roles (80-100%), graduate programs.
- **Eligible:** Starts after graduation.
- **Value:** Role and salary fit; growth.
- **CV slot:** Available full-time after graduation.
