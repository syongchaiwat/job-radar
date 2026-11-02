"""Stage-log rules (src/tracking/core.py) on an in-memory database."""
from datetime import date, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from src.db import Job, Tracking
from src.tracking import core


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Job(id="j1", source="manual", url="https://example.com/1", company="Acme", title="Data Scientist"))
        s.commit()
        yield s


def status(session):
    return session.get(Tracking, 1).status if session.get(Tracking, 1) else "new"


def days(n):
    return (date.today() + timedelta(days=n)).isoformat()


def test_triage_is_a_single_choice_and_resets(session):
    core.log_stage(session, "j1", "shortlist")
    core.log_stage(session, "j1", "skipped")
    assert [e.stage for e in core.events_for(session, "j1")] == ["skipped"]
    core.reset_triage(session, "j1")
    assert core.events_for(session, "j1") == [] and status(session) == "new"


def test_process_stage_adds_missing_applied(session):
    core.log_stage(session, "j1", "shortlist")
    core.log_stage(session, "j1", "interview", on=days(-2), applied_on=days(-10))
    stages = [(e.stage, e.date) for e in core.events_for(session, "j1")]
    assert stages == [("applied", days(-10)), ("interview", days(-2))]  # shortlist dropped once applied
    assert status(session) == "interview"


def test_applied_date_after_entry_is_rejected(session):
    with pytest.raises(core.StageError):
        core.log_stage(session, "j1", "rejected", on=days(-5), applied_on=days(-1))


def test_interview_rounds_number_themselves(session):
    core.log_stage(session, "j1", "applied", on=days(-20))
    core.log_stage(session, "j1", "interview", on=days(-10))
    ev = core.log_stage(session, "j1", "interview", on=days(-3))
    assert core.detail_of(ev)["round"] == 2 and core.event_label(ev) == "Interview 2"


def test_outcome_closes_and_needs_reopen(session):
    core.log_stage(session, "j1", "applied", on=days(-20))
    core.log_stage(session, "j1", "interview", on=days(-10))
    core.log_stage(session, "j1", "rejected", on=days(-5))
    s = core.summary(core.events_for(session, "j1"))
    assert s["closed"] and s["stage_label"] == "Rejected after Interview 1" and s["reached"] == 4
    with pytest.raises(core.NeedsReopen):
        core.log_stage(session, "j1", "interview", on=days(-1))
    core.log_stage(session, "j1", "interview", on=days(-1), reopen=True)
    assert status(session) == "interview"


def test_triage_after_applying_and_offer_rules(session):
    core.log_stage(session, "j1", "applied", on=days(-20))
    with pytest.raises(core.StageError):
        core.log_stage(session, "j1", "skipped")
    with pytest.raises(core.StageError):
        core.log_stage(session, "j1", "accepted")  # needs an Offer
    with pytest.raises(core.StageError):
        core.log_stage(session, "j1", "applied")  # only one


def test_deleting_applied_removes_the_application(session):
    core.log_stage(session, "j1", "applied", on=days(-20))
    core.log_stage(session, "j1", "screening", on=days(-15))
    core.delete_event(session, core.events_for(session, "j1")[0])
    assert core.events_for(session, "j1") == [] and status(session) == "new"


def test_next_action(session):
    core.log_stage(session, "j1", "applied", on=days(-30))
    assert core.next_action(core.events_for(session, "j1"))["kind"] == "follow_up"
    core.log_stage(session, "j1", "screening", on=days(-2), time="10:00")
    assert core.next_action(core.events_for(session, "j1"))["kind"] == "debrief"
    core.log_stage(session, "j1", "interview", on=days(3), time="14:00")
    nxt = core.next_action(core.events_for(session, "j1"))
    assert nxt["kind"] == "upcoming" and nxt["label"] == "Interview 1"


def test_ics_has_one_event_per_entry(session):
    ev = core.log_stage(session, "j1", "interview", on=days(3), time="14:00", applied_on=days(-5))
    body = core.ics([(ev, "Interview 1: Acme, Data Scientist")])
    assert body.count("BEGIN:VEVENT") == 1 and "TZID=Europe/Zurich" in body and "Acme\\, Data Scientist" in body
