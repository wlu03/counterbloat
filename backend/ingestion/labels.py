"""Collect the outcome events a company filed about itself.

Item 4.02 of an 8-K is the company stating that previously issued financial statements should no
longer be relied on. It is a filed event with a date, not a judgement, and the submissions feed
lists the item numbers of every 8-K, so no document has to be read to find one.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.ingestion.edgar import OLDER, SUBMISSIONS, pad, read_json

NON_RELIANCE = "4.02"


@dataclass(frozen=True)
class Event:
    cik: str
    item: str
    filed_at: str
    accession: str


def _scan(cik: str, block: dict, item: str) -> list[Event]:
    return [Event(cik=cik, item=item, filed_at=date, accession=accession)
            for form, items, date, accession in zip(
                block["form"], block["items"], block["filingDate"], block["accessionNumber"])
            if form.startswith("8-K") and item in (items or "").split(",")]


def events(cik: str, item: str = NON_RELIANCE, include_older: bool = False) -> list[Event]:
    """Every 8-K a company filed carrying one item number, newest first.

    The older submissions files are read only when asked for, because each is another request and
    a restatement that matters for a recent call is in the inline block.
    """
    cik = pad(cik)
    submissions = read_json(SUBMISSIONS.format(cik=cik))["filings"]
    found = _scan(cik, submissions["recent"], item)
    if include_older:
        for older in submissions.get("files", []):
            found.extend(_scan(cik, read_json(OLDER.format(name=older["name"])), item))
    return sorted(found, key=lambda e: e.filed_at, reverse=True)


def within(found: list[Event], start: str, months: int) -> list[Event]:
    """Events filed between a call date and a horizon after it, both as YYYY-MM-DD."""
    year, month = int(start[:4]), int(start[5:7])
    month += months
    end = f"{year + (month - 1) // 12:04d}-{(month - 1) % 12 + 1:02d}-{start[8:10]}"
    return [e for e in found if start <= e.filed_at <= end]
