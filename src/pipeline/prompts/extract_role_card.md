You are condensing a job posting into a normalized role card. Role cards are compared with each other to group similar jobs and to measure which skills the market asks for, so they must describe the role itself, consistently, and nothing else.

## Rules
- Write everything in **English**, even if the posting is in German, French or another language. Only `raw_term` keeps the original wording.
- Describe the role, not the company: leave out company marketing, benefits, culture statements, application instructions and legal text.
- Skills are concrete skills, tools, frameworks, platforms and methods (e.g. Python, SQL, PyTorch, Kubernetes, A/B testing, time-series forecasting, credit risk modeling). Do not list soft skills ("communication", "team player") or degrees.
- For each skill, if the same concept is in the known-skills list below, use that **exact** name. Otherwise propose a short conventional name. Split combined terms ("Python/R" → Python, R).
- `importance`: "required" for must-haves, "nice_to_have" for "a plus", "advantageous", "ideally".
- Lane signals: report only what the posting states. "Werkstudent" / "working student" → working_student; "Praktikum" / "internship" → internship; a posting offering a master's thesis → thesis. Leave fields empty when not stated.
- Do not invent anything that isn't in the posting. If the posting is short or vague, say so with `information_quality: thin` rather than filling gaps.

## Known skills (use these exact names when the concept matches)
{known_skills}

## Job posting
Title: {job_title}
Company: {job_company}
Location: {job_location}

{job_description}
