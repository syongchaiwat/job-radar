"""FastAPI app entry point. Run with: uvicorn app.main:app --reload --port 8000"""
from pathlib import Path

from dotenv import load_dotenv

# Must run before any import that touches src.pipeline.llm_config, which reads
# LLM_PROVIDER at import time -- without this the app silently falls back to
# the Anthropic default and fails with an auth error instead of using Ollama.
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app.routes import board, classify, job_detail, market, profile, skills  # noqa: E402
from src.db import get_engine, init_db  # noqa: E402

app = FastAPI(title="job-radar")

# Only CLI scripts called init_db() before this -- a server started fresh
# against a DB missing a newer table (e.g. cv_draft) would otherwise 500 on
# first use instead of creating it.
init_db(get_engine())

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(board.router)
app.include_router(job_detail.router)
app.include_router(profile.router)
app.include_router(skills.router)
app.include_router(classify.router)
app.include_router(market.router)
