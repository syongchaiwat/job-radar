"""FastAPI dependencies."""
from typing import Iterator

from sqlmodel import Session

from src.db import get_engine

_engine = get_engine()


def get_session() -> Iterator[Session]:
    with Session(_engine) as session:
        yield session
