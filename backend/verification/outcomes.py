"""Report what the company later said about the figures it was discussing.

Item 4.02 of an 8-K is the company stating that previously issued financial statements should no
longer be relied on. It is reported as context and never as a contradiction: a filing months after
a call does not show that any particular sentence on that call was wrong, only that the numbers
the call drew on were later withdrawn. Deciding what that means about a claim is a reader's job.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.ingestion.labels import NON_RELIANCE, events, within
from backend.models import Relationship

AGENT = "outcome-checker"
TIER = "external"
CONTEXT, NOT_FOUND = "context", "not_found"
DEFAULT_MONTHS = 24


@dataclass(frozen=True)
class Outcome:
    claim_id: str
    stance: str
    agent: str = AGENT
    tier: str = TIER
    item: str | None = None
    filed_at: str | None = None
    accession: str | None = None
    months_after: int | None = None
    relationship: Relationship | None = None
    note: str = ""


def _months_between(start: str, end: str) -> int:
    return (int(end[:4]) - int(start[:4])) * 12 + int(end[5:7]) - int(start[5:7])


def check(claim_id: str, cik: str, call_date: str, months: int = DEFAULT_MONTHS) -> Outcome:
    """The first non-reliance filing within the window after the call, if the company made one."""
    found = within(events(cik, NON_RELIANCE), call_date, months)
    if not found:
        return Outcome(claim_id, NOT_FOUND,
                       note=f"no non-reliance filing in the {months} months after the call")
    first = min(found, key=lambda e: e.filed_at)
    return Outcome(claim_id, CONTEXT, item=first.item, filed_at=first.filed_at,
                   accession=first.accession,
                   months_after=_months_between(call_date, first.filed_at),
                   relationship=Relationship.context,
                   note=("the company later said earlier financial statements should not be "
                         "relied on; this is context for the call, not a finding about the claim"))
