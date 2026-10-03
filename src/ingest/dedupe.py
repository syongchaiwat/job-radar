"""Shared job-id hashing and dedupe check. Used by every ingestion source and by seed_db.py."""
import hashlib

from sqlmodel import Session

from src.db import Job


def job_id(url: str) -> str:
    return hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:16]


def is_duplicate(session: Session, url: str) -> bool:
    return session.get(Job, job_id(url)) is not None
