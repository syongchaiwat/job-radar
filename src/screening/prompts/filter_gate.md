You are screening a Swiss job posting against a candidate's explicit filter rules.

## Candidate's filter rules
{filters}

## Job posting
Title: {job_title}
Company: {job_company}
Location: {job_location}
Level/seniority text: {job_level}

Description:
{job_description}

## Task
Decide: "keep" (no concerns), "exclude" (clearly violates an Exclude rule), or "flag" (keep it, but a Flag rule applies or something is concerning enough to note).
Cite the specific rule(s) that applied in your reasons, quoting the relevant part of the job posting where useful. If nothing applies, decision is "keep" with an empty reasons list.

Note: the title has already been checked programmatically against the "Titles containing Senior, Staff, Principal, Lead, Head of, Director" rule and does not match it -- do not cite that rule as a reason, and do not extend it to words it doesn't list (e.g. "Manager" is not on that list).
