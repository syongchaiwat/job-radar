You are extracting a career event from a raw web page dump: a career fair, company workshop, info session, open house, case challenge, networking evening or similar. The text below is the stripped-of-HTML-tags text of the page, so it's noisy: navigation menus, cookie banners, other events and footer text are mixed in with the real content.

## Raw page text
{page_text}

## Task
Pull out:
- event: the event's name (e.g. "Open House: Career Information Session")
- host: the organising company or organisation
- date: the event date as YYYY-MM-DD (the first day if it spans several); assume the next occurrence of that date after {today} if no year is given
- time: start time as HH:MM (24h), if stated
- location: venue and/or city, or "Online"
- registration_deadline: YYYY-MM-DD, if stated
- description: the event's real content -- agenda, who it's for, requirements, how to register -- with page chrome stripped out. Keep it close to verbatim; don't summarize.

If a field genuinely isn't present, return an empty string for it rather than guessing. If the page holds no event content at all, return empty strings for every field.
