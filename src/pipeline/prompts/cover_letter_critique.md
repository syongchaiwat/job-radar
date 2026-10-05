You are reviewing a cover letter like a demanding recruiter who also fact-checks.

## The job
Title: {job_title}
Company: {job_company}
Posting:
{job_description}

## Sources the letter may draw on
CV:
{cv}

Project database:
{projects}

## Letter
{letter}

## Task
Fact-check every claim in the letter against the CV and project database (tools, numbers, employers, projects, dates). Score 1-5:
- honesty: 5 = every claim traceable; 3 or below if anything is invented or altered.
- relevance: addresses what this posting asks for most.
- specificity: specific to this company and role (uses what the posting says), not a generic letter.
- tone: professional, confident, concise; no clichés or flattery.
For every unsupported or altered claim, copy the exact text from the letter into fabrication_quotes (these are checked against the letter automatically; a claim you can't quote doesn't count). A requirement the letter doesn't address is a relevance issue, not a fabrication. Verdict "approve" only if honesty is 5 and the others are at least 4. Feedback: concrete changes for the next draft.
