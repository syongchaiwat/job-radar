"""Lab outreach entries (Job.kind == "outreach"): stage names and rules, stats split, default CV."""
from datetime import date, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.cv import library
from src.db import Job
from src.tracking import core, stats


def days(n):
    return (date.today() + timedelta(days=n)).isoformat()


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(library, "CV_DRAFTS_DIR", tmp_path / "cv_drafts")
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Job(id="lab", source="manual", url="https://example.com/lab", company="Some Lab", title="Thesis: ML", kind="outreach"))
        s.add(Job(id="job", source="manual", url="https://example.com/job", company="Acme", title="Data Scientist"))
        s.commit()
        yield s


def summary(session, job_id="lab", kind="outreach"):
    return core.summary(core.events_for(session, job_id), kind)


def test_new_lab_reads_to_contact(session):
    s = summary(session)
    assert s["status_label"] == "To contact" and s["stage_label"] == "To contact" and not s["applied"]


def test_outreach_names_and_closing_label(session):
    core.log_stage(session, "lab", "applied", on=days(-20), kind="outreach")
    core.log_stage(session, "lab", "screening", on=days(-10), kind="outreach")
    core.log_stage(session, "lab", "interview", on=days(-5), kind="outreach")
    core.log_stage(session, "lab", "rejected", on=days(-1), kind="outreach")
    s = summary(session)
    assert [e["label"] for e in s["events"]] == ["Sent", "Replied", "Meeting 1", "No topic"]
    assert s["stage_label"] == "No topic after Meeting 1"
    assert [st["label"] for st in s["stepper"]] == ["Sent", "Replied", "Meeting", "Topic offered"]


def test_job_only_stages_are_refused_for_labs(session):
    for stage in ("assessment", "shortlist", "closed"):
        with pytest.raises(core.StageError):
            core.log_stage(session, "lab", stage, kind="outreach")
    core.log_stage(session, "job", "shortlist")  # still fine for a job


def test_a_reply_is_not_a_meeting(session):
    core.log_stage(session, "lab", "applied", on=days(-3), kind="outreach")
    core.log_stage(session, "lab", "screening", on=days(-1), kind="outreach")
    s = summary(session)
    assert not s["events"][-1]["needs_debrief"] and s["next"] is None  # a reply needs no debrief
    core.log_stage(session, "lab", "interview", on=days(-1), kind="outreach")
    assert summary(session)["next"]["label"] == "How did Meeting 1 go?"


def test_follow_up_after_quiet_weeks(session):
    core.log_stage(session, "lab", "applied", on=days(-core.FOLLOW_UP_DAYS), kind="outreach")
    assert summary(session)["next"]["kind"] == "follow_up"


def test_labs_stay_out_of_job_stats(session):
    core.log_stage(session, "lab", "applied", on=days(-9), kind="outreach")
    core.log_stage(session, "lab", "screening", on=days(-2), kind="outreach")
    core.log_stage(session, "job", "applied", on=days(-4))
    session.commit()
    assert stats.application_stats(session)["n"] == 1
    o = stats.outreach_stats(session)
    assert (o["n"], o["to_contact"], o["sent"], o["replied"], o["median_days_to_reply"]) == (1, 0, 1, 1, 7)


def test_labs_default_to_the_newest_thesis_cv(session):
    assert library.cv_for_job(session, session.get(Job, "lab")) is None
    library.create_custom(session, "General", "general", markdown="## Summary\n\ng")
    thesis = library.create_custom(session, "Thesis", "thesis", markdown="## Summary\n\nt")
    cv = library.cv_for_job(session, session.get(Job, "lab"))
    assert cv is not None and cv.custom_cv_id == thesis.id
    assert library.cv_for_job(session, session.get(Job, "job")) is None  # jobs never fall back to own CVs
