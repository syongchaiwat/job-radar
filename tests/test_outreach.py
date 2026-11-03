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


# --- events (Job.kind == "event") ---------------------------------------------------------

@pytest.fixture
def ev_session(session):
    session.add(Job(id="ev", source="manual", url="https://example.com/ev", company="Host", title="Open House", kind="event"))
    session.commit()
    return session


def test_event_names_and_attended_once_past(ev_session):
    core.log_stage(ev_session, "ev", "shortlist", kind="event")
    assert summary(ev_session, "ev", "event")["stage_label"] == "Interested"
    core.log_stage(ev_session, "ev", "applied", on=days(-10), kind="event")
    core.log_stage(ev_session, "ev", "interview", on=days(3), time="17:30", kind="event")
    s = summary(ev_session, "ev", "event")
    assert [e["label"] for e in s["events"]] == ["Registered", "Event"]
    assert s["next"]["kind"] == "upcoming" and s["next"]["label"] == "Event"
    assert [st["label"] for st in s["stepper"]] == ["Registered", "Confirmed", "Event"]
    ev = core.events_for(ev_session, "ev")[-1]
    core.update_event(ev_session, ev, on=days(-1), time="17:30")
    s = summary(ev_session, "ev", "event")
    assert s["events"][-1]["label"] == "Attended" and s["next"]["label"] == "How did the event go?"


def test_events_refuse_job_only_stages_and_never_nag(ev_session):
    for stage in ("assessment", "offer", "accepted"):
        with pytest.raises(core.StageError):
            core.log_stage(ev_session, "ev", stage, kind="event")
    core.log_stage(ev_session, "ev", "applied", on=days(-40), kind="event")
    assert summary(ev_session, "ev", "event")["next"] is None  # no follow-up nudge for events
    core.log_stage(ev_session, "ev", "rejected", on=days(-30), kind="event")
    assert summary(ev_session, "ev", "event")["stage_label"] == "Not selected"


def test_events_stay_out_of_job_stats_and_use_no_default_cv(ev_session):
    core.log_stage(ev_session, "ev", "applied", on=days(-2), kind="event")
    ev_session.commit()
    assert stats.application_stats(ev_session)["n"] == 0 and stats.outreach_stats(ev_session)["n"] == 1
    library.create_custom(ev_session, "Thesis", "thesis", markdown="## Summary\n\nt")
    assert library.cv_for_job(ev_session, ev_session.get(Job, "ev")) is None
