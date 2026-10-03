"""Lazy, on-demand description breakdown for the Job Detail page.

Deliberately NOT a graph node: unlike the screening pipeline (run for every
job during ingestion/batch screening), this only runs when a job's detail
page is actually opened, and the result is cached on Job.description_breakdown
so a second view is instant. See app/routes/job_detail.py for the caching
call site.
"""
from src.db import Job
from src.pipeline.llm_call import call, load_prompt, truncate
from src.pipeline.schemas import DescriptionBreakdown


def compute_breakdown(job: Job) -> DescriptionBreakdown:
    prompt = load_prompt("breakdown_description").format(
        job_title=job.title,
        job_company=job.company,
        job_description=truncate(job.description),
    )
    parsed, _log = call("fast", prompt, DescriptionBreakdown)
    return parsed
