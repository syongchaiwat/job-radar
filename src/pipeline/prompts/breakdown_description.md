You are restructuring a raw job posting description into a fixed set of sections for display.

## Job posting
Title: {job_title}
Company: {job_company}

Raw description:
{job_description}

## Task
Extract into exactly these four sections:
- about_the_role: 1-3 sentences on what the role/team actually does.
- key_responsibilities: bullet list of concrete day-to-day responsibilities. Empty list if the posting doesn't distinguish these.
- requirements_skills: bullet list of required skills/qualifications/experience.
- nice_to_have: bullet list of explicitly optional/preferred qualifications. Empty list if the posting doesn't distinguish "nice to have" from requirements.

Write every section in **English**, translating faithfully if the posting is in German, French or another language (keep product names and technical terms as they are).

Only use information present in the text above -- if the description is truncated or thin, keep sections short or empty rather than inventing content. Do not fabricate responsibilities or requirements not evidenced in the text.
