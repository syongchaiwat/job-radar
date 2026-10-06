You are extracting a job posting from a raw web page dump. The text below is the stripped-of-HTML-tags text of an entire job listing page, so it's noisy: navigation menus, cookie banners, "similar jobs" lists, footer legal text, and other page chrome are mixed in with the actual posting.

## Raw page text
{page_text}

## Task
Pull out:
- The job title
- The hiring company's name (the actual employer, not a recruiting agency, if the agency is named separately)
- The location, if stated
- The actual job posting content -- role description, responsibilities, requirements, benefits -- with all the page chrome (nav, cookie banner, unrelated job listings, footer) stripped out. Keep the real content close to verbatim; don't summarize or paraphrase it.

If a field genuinely isn't present in the text, return an empty string for it rather than guessing.

If the page holds no actual job posting -- a search-results or job-recommendations page, a login wall, or a page shell whose posting loads later via JavaScript (only navigation, filters and footer text) -- return empty strings for every field. Never describe the website itself as if it were the job.
