"""Own CVs in the library (src/cv/library.py) and the cvversion rebuild (src/db.py)."""
import json

import pytest
from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine, select

from src.cv import library
from src.db import CVVersion, Job, get_engine, init_db
from src.lanes import core as lanes


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(library, "CV_DRAFTS_DIR", tmp_path / "cv_drafts")
    monkeypatch.setattr(library, "profile_hash", lambda: "profile-1")
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_pasted_cv_starts_as_hand_written_v1(session):
    custom = library.create_custom(session, "Thesis: ML", "thesis", markdown="# Name\r\n\r\n## Summary\r\n\r\nText.")
    vs = library.versions(session, library.custom_slug(custom))
    assert len(vs) == 1
    assert vs[0].verdict == "hand-written" and vs[0].archetype_id is None and vs[0].custom_cv_id == custom.id
    assert "\r" not in vs[0].draft_markdown
    assert library.custom_status(vs[0])["outdated"] is False  # hand-written never goes stale


def test_edit_keeps_the_cv_and_adds_a_version(session):
    custom = library.create_custom(session, "General", "general", markdown="## Summary\n\nOne.")
    base = library.versions(session, library.custom_slug(custom))[0]
    library.save_edit(session, base, "## Summary\n\nTwo.\n")
    vs = library.versions(session, library.custom_slug(custom))
    assert [v.draft_markdown.strip() for v in vs] == ["## Summary\n\nOne.", "## Summary\n\nTwo."]
    assert vs[-1].custom_cv_id == custom.id


def test_ai_draft_uses_the_brief_and_thesis_rules(session, monkeypatch):
    session.add(Job(id="lab1", source="manual", url="https://example.com/lab", company="Some Lab", title="Research",
                    description="We study learning systems."))
    session.commit()
    custom = library.create_custom(session, "Thesis: ML", "thesis", brief="Emphasise deep learning.", context_job_ids=["lab1"])
    seen = {}

    class FakeGraph:
        def invoke(self, state):
            seen.update(state)
            return {**state, "draft_markdown": "## Summary\n\nDraft. · source: X", "verdict": "approve", "attempt_count": 1}

    monkeypatch.setattr(library, "GRAPH", FakeGraph())
    cv = library.generate_custom(session, custom.id)
    assert "Emphasise deep learning." in seen["job_description"] and "We study learning systems." in seen["job_description"]
    assert seen["target_note"] == library.THESIS_NOTE and "ALWAYS include" in seen["target_note"]
    assert cv.custom_cv_id == custom.id and cv.archetype_slug == library.custom_slug(custom)
    assert "source:" not in cv.draft_markdown  # template metadata stripped
    assert json.loads(cv.source_job_ids) == ["lab1"]
    monkeypatch.setattr(library, "profile_hash", lambda: "profile-2")
    assert library.custom_status(cv)["outdated"] is True


def test_archived_cvs_leave_the_list_but_keep_their_name(session):
    custom = library.create_custom(session, "Old one", "general", markdown="## Summary\n\nx")
    custom.archived = True
    session.add(custom)
    session.commit()
    assert library.customs(session) == []
    assert library.cv_names(session)[library.custom_slug(custom)] == "Old one"


def test_outreach_lane_is_never_a_job_lane(monkeypatch):
    monkeypatch.setattr(lanes, "lanes_text", lambda: (
        "## Full-time\n- **Key:** full-time\n- **CV slot:** Available.\n\n"
        "## Thesis at a lab\n- **Key:** academic-thesis\n- **CV slot:** Looking for a thesis.\n"))
    assert [l.key for l in lanes.job_lanes()] == ["full-time"]
    assert lanes.lane_by_key("academic-thesis").slot == "Looking for a thesis."


OLD_CVVERSION = """CREATE TABLE cvversion (
    id INTEGER NOT NULL, archetype_id INTEGER NOT NULL, archetype_slug VARCHAR NOT NULL, draft_markdown VARCHAR NOT NULL,
    attempt_count INTEGER NOT NULL, verdict VARCHAR NOT NULL, relevance_score INTEGER, honesty_score INTEGER,
    impact_score INTEGER, clarity_score INTEGER, keyword_alignment_score INTEGER, overall_feedback VARCHAR,
    unresolved_gaps VARCHAR NOT NULL, source_job_ids VARCHAR NOT NULL, market_hash VARCHAR NOT NULL,
    profile_hash VARCHAR NOT NULL, model_used VARCHAR, tokens INTEGER, latency_ms FLOAT, file_path VARCHAR,
    created_at DATETIME NOT NULL, PRIMARY KEY (id))"""


def test_rebuild_relaxes_archetype_id_and_keeps_rows(tmp_path):
    engine = get_engine(str(tmp_path / "old.db"))
    with engine.begin() as conn:
        conn.execute(text(OLD_CVVERSION))
        conn.execute(text("CREATE INDEX ix_cvversion_archetype_slug ON cvversion (archetype_slug)"))
        conn.execute(text("INSERT INTO cvversion VALUES (7, 1, 'ml', '# CV', 1, 'approve', 5, 5, 4, 4, 4, NULL, '[]', '[]', "
                          "'m', 'p', 'sonnet', 10, 1.0, NULL, '2026-10-01 00:00:00')"))
    init_db(engine)
    init_db(engine)  # idempotent
    cols = {c["name"]: c for c in inspect(engine).get_columns("cvversion")}
    assert cols["archetype_id"]["nullable"] and "custom_cv_id" in cols
    with Session(engine) as s:
        row = s.exec(select(CVVersion)).one()
        assert (row.id, row.archetype_slug, row.draft_markdown) == (7, "ml", "# CV")
