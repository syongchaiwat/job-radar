You are extracting the job title and hiring company name from a pasted job posting. The person who added this posting didn't type them in manually, so they need to be pulled out of the raw text below.

## Job posting text
{job_description}

## Task
Extract the job title and the hiring company's name, exactly as they appear in the text (don't paraphrase or normalize them). If the posting is via a recruiting agency, use the actual hiring company if it's named, not the agency. If either genuinely cannot be determined from the text, return an empty string for that field rather than guessing.
