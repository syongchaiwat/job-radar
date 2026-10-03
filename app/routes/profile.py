"""Profile page: GET /profile

Port of the old Streamlit Profile page: per-theme screened-job counts,
gap-keyword frequency (simple watchlist substring count against real
Screening.gaps text -- deliberately simple v1, not NLP clustering),
low-hanging fruit pulled live from each theme's profile file, and the
Art. 21 FNIA permit countdown from constraints.md.
"""
import json
import re
from collections import Counter
from datetime import date

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from app.constants import THEME_NAMES
from app.deps import get_session
from app.services.render import markdown_bullets_to_list
from app.templating import templates
from src.db import Job, Screening
from src.pipeline import profile_context as pc

router = APIRouter()

GRADUATION = date(2027, 6, 30)
PERMIT_DEADLINE = date(2027, 12, 31)

WATCHLIST = [
    "Kubernetes", "Docker", "FastAPI", "AWS", "GCP", "Azure", "Kafka", "Spark", "Airflow",
    "PyTorch", "TensorFlow", "FRM", "CFA", "German", "derivatives", "RAG", "LangChain",
    "LangGraph", "eval", "vector database", "S3", "Redshift", "Terraform",
]


@router.get("/profile")
def profile(request: Request, session: Session = Depends(get_session)):
    today = date.today()

    rows = session.exec(select(Job, Screening).join(Screening, Job.id == Screening.job_id)).all()

    gaps_by_theme: dict[str, list[str]] = {t: [] for t in THEME_NAMES}
    counts_by_theme: dict[str, int] = {t: 0 for t in THEME_NAMES}
    for job, sc in rows:
        if sc.theme in gaps_by_theme:
            counts_by_theme[sc.theme] += 1
            if sc.gaps:
                gaps_by_theme[sc.theme].extend(json.loads(sc.gaps))

    theme_sections = []
    for theme_code, theme_name in THEME_NAMES.items():
        gaps = gaps_by_theme[theme_code]
        top_gaps = []
        if gaps:
            text_blob = " | ".join(gaps).lower()
            counts = Counter({term: text_blob.count(term.lower()) for term in WATCHLIST})
            counts = Counter({k: v for k, v in counts.items() if v > 0})
            top_gaps = counts.most_common(8)

        theme_file = pc.load_theme(theme_code)
        m = re.search(r"## Low-hanging fruit\n(.+?)(?:\n##|\Z)", theme_file, re.DOTALL)
        low_hanging_fruit_items = markdown_bullets_to_list(m.group(1)) if m else []

        theme_sections.append(
            {
                "code": theme_code,
                "name": theme_name,
                "n_jobs": counts_by_theme[theme_code],
                "top_gaps": top_gaps,
                "low_hanging_fruit_items": low_hanging_fruit_items,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="profile.html",
        context={
            "days_to_graduation": (GRADUATION - today).days,
            "days_to_permit_deadline": (PERMIT_DEADLINE - today).days,
            "theme_sections": theme_sections,
        },
    )
