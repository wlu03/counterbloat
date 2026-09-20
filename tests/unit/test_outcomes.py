from backend.ingestion.labels import Event
from backend.models import Relationship
from backend.verification import outcomes

EVENTS = [Event(cik="0000012345", item="4.02", filed_at="2016-03-01", accession="a-2"),
          Event(cik="0000012345", item="4.02", filed_at="2015-09-10", accession="a-1")]


def test_a_later_non_reliance_filing_is_reported_as_context(monkeypatch):
    monkeypatch.setattr(outcomes, "events", lambda cik, item: EVENTS)
    found = outcomes.check("c1", "0000012345", "2015-04-22", months=24)
    # The earliest filing inside the window is the one reported.
    assert found.stance == outcomes.CONTEXT and found.accession == "a-1"
    assert found.months_after == 5 and found.relationship is Relationship.context
    assert "not a finding about the claim" in found.note


def test_a_filing_outside_the_window_is_not_reported(monkeypatch):
    monkeypatch.setattr(outcomes, "events", lambda cik, item: EVENTS)
    found = outcomes.check("c1", "0000012345", "2015-04-22", months=3)
    assert found.stance == outcomes.NOT_FOUND and found.accession is None


def test_a_company_that_never_filed_one_is_not_found(monkeypatch):
    monkeypatch.setattr(outcomes, "events", lambda cik, item: [])
    assert outcomes.check("c1", "0000012345", "2015-04-22").stance == outcomes.NOT_FOUND


def test_the_outcome_never_counts_as_a_contradiction(monkeypatch):
    monkeypatch.setattr(outcomes, "events", lambda cik, item: EVENTS)
    found = outcomes.check("c1", "0000012345", "2015-04-22")
    assert found.relationship is not Relationship.contradicts
    assert found.stance != "contradicts"
