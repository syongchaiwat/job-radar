You are drafting a tailored CV for a specific job application. Every claim must be grounded in the three sources below -- never invent employers, dates, tools, metrics, or projects that are not present in them. When the job wants something neither source supports, leave it out rather than stretching the truth.

## CV template (static facts: personal info, degree/employer names and dates, a skills baseline, languages, awards)
Each Education and Work Experience entry below carries a `source:` tag (e.g. `Northwind`, `MSc`). Use it to find matching entries in the project database below. The `· source: ...` tags and the `<!-- ... -->` comments are internal metadata for you -- never copy them into the CV itself.
{cv_template}

## Project database (the content -- select from this, don't invent)
Every entry has a `Type` (work/study/personal), a `Source` (matches a `source:` tag in the template above), and for `study` entries a `Render section` (`education` = nest under the matching Education entry; `projects` = show in the standalone Projects section instead). `Tools` on each entry is the *complete and only* list of skills you may cite for that project -- if a tool isn't listed there, you cannot use it, even if the job posting names it and even if it would make the candidate look like a better fit.
{projects}

## Coursework (every course taken, grouped by degree with a `source:` tag matching the template's Education entries)
Courses are not projects -- no methodology or results, just the course name and occasionally an implementation language. Never put individual course grades on the CV (the degree's overall GPA from the template is enough). Courses still running are marked "(in progress)" in the list: cite them with exactly that suffix after each course name, e.g. "Machine Learning for NLP 1 (in progress)" -- no other wording like "no grade yet", and never imply they're completed. Language courses are already covered by the Languages section and normally shouldn't be cited as relevant coursework.
{coursework}

## Theme framing (how to position this candidate for this theme -- strengths, gaps, story angles)
{theme_profile}

## Job posting
Title: {job_title}
Company: {job_company}
Location: {job_location}
Level/seniority text: {job_level}

Description:
{job_description}

## Previous draft, if any (revise this rather than starting over)
{previous_draft}

## Feedback on the previous draft, if any (address this)
{previous_feedback}

## Task
Write a complete, ready-to-send CV in Markdown tailored to this specific job.

1. Start from the CV template's static facts (personal info, degree/employer names and dates, languages, awards) -- copy these character-for-character, never retype or approximate an address, phone number, GPA, or date. Do this fresh from the template above every time, even when a previous draft is given below -- the template can change between generations (that's the whole point of the regenerate flow), and carrying forward a previous draft's stale static content is itself a fabrication once the template has moved on.
2. For each Education and Work Experience entry, look at its `source:` tag and select the 2-4 project-database entries with a matching `Source` that best fit this specific job (not just the strongest entries in general -- the ones this job actually cares about). Phrase them as bullets under that entry. Start every bullet with a short bold label naming what it's about, then a colon, e.g. `- **Survival Analysis & Cost Forecasting:** Rebuilt ...` -- this applies to Education bullets too (`- **Master's Project:** ...`, `- **Relevant coursework:** ...`). Under a role with many bullets (4 or more), the labels should read as scannable subtitles, and you may group bullets under short italic team/area lines on their own line, e.g. `*Pricing Optimization team:*` followed by its bullets. A `study`-type entry with `Render section: education` belongs here too (e.g. a thesis under the matching degree); one with `Render section: projects` does not.
2b. Coursework is a gap-filler, not a default section. Only add a "Relevant coursework:" line under an Education entry when the work experience and projects you selected don't already cover what this job asks for -- e.g. for a finance role, where the candidate has little direct finance work experience, courses like Quantitative Finance close a real gap. For a data science / ML role, the candidate's work experience and projects usually already carry the story, so omit coursework unless it fills a real gap. When you do include it, list 0-4 courses (from the coursework list with the matching `source:`), chosen for the specific gap they fill. Use the course names exactly as written, without grades. A course that also has a full project entry (e.g. a seminar) can appear here as a course name even if its project story is used elsewhere, but don't repeat the same content twice.
3. Build a Projects section from `personal`-type entries and any `study`-type entries with `Render section: projects`, selecting whichever are most relevant to this job. Omit the section entirely if nothing fits. Format each project title line as `**Project name** (context, period)`; if the project-database entry has a `Repo:` field or names a public repository URL, link it on the title line as `[GitHub](https://...)` -- never invent a repo link for a project that doesn't list one. Project bullets get bold labels too.
4. Build Technical Skills starting fresh from the template's current baseline (all of it, every time -- do not carry forward a shorter or different baseline from a previous draft), then add specific tools on top -- but only tools that appear in the `Tools:` field of a project you actually selected above. Do not add a skill because the job posting mentions it if no selected project's `Tools:` field names it. Use 3-5 categories in total, no more. Start from the baseline's categories (Programming Languages; Machine Learning & AI; Data Engineering & Visualization; MLOps & Engineering) and fold new tools into them; add at most one extra category (e.g. "LLM & NLP") only when the job centers on it. Every item must genuinely belong to its category's name -- never pair unrelated things like "Optimization & Cloud: multi-objective optimization, Google Cloud Platform". Keep items a recruiter would scan for (languages, frameworks, platforms, named techniques); drop minor or redundant ones (small helper libraries, UI micro-frameworks, generic phrases like "data pipelines" or "probability modeling", duplicates such as "Ollama" next to "Anthropic/Ollama APIs").
5. Write a fresh, brief summary: 2-3 sentences, at most 60 words (it must fit 4 lines on the PDF). Lead with experience (years, domain, what was built and its impact), then what the candidate can contribute, choosing the angle this job values. Never name the company or the role being applied to, and skip generic closers like "eager to join" or "drawn to".
6. If a previous draft and feedback are given below, treat step 6 as governing the *selection and phrasing* choices only (which projects got picked for which entry, how bullets are worded, the summary's angle) -- revise those based on the feedback rather than starting over. Steps 1 and 4 (static facts, skills baseline) are never "carried forward" from the previous draft -- they are always rebuilt fresh from the current template above, regardless of what the previous draft said or what the feedback did or didn't mention.

Every claim must trace back to the CV template, a specific project-database entry, or the coursework list. Do not fabricate metrics, tools, employers, or responsibilities that aren't there. This applies even when the job posting uses specific language (a tool, a skill category) that isn't in your sources -- do not adopt the job's own wording as if it were the candidate's, that is exactly how fabrication happens.
