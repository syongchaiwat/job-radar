You are extracting a university research lab's page from a raw web page dump, for a student who wants to ask the lab about master's thesis topics. The text below is the stripped-of-HTML-tags text of the page, so it's noisy: navigation menus, cookie banners, news lists, footer text and other page chrome are mixed in with the lab's real content.

## Raw page text
{page_text}

## Task
Pull out:
- lab: the lab or research group's name (e.g. "Medical Data Science group"), with its institution if stated (e.g. "…, ETH Zurich")
- professor: the head of the lab (name only), if stated
- research_area: a short phrase (3-8 words) for what the lab works on
- location: city if stated
- description: the lab's real content -- research topics, projects, open student / thesis projects, requirements, how to apply, contact instructions -- with page chrome stripped out. Keep it close to verbatim; don't summarize.

If a field genuinely isn't present, return an empty string for it rather than guessing. If the page holds no lab content at all (a login wall, an empty shell), return empty strings for every field.
