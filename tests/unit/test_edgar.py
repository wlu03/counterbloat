import json

import pytest

from backend.ingestion import edgar
from backend.ingestion.fetch import FetchError

OLDER_NAME = "CIK0000320193-submissions-001.json"

SUBMISSIONS = {"filings": {"files": [{"name": OLDER_NAME}], "recent": {
    "form": ["10-K", "8-K", "10-Q"],
    "accessionNumber": ["0000320193-24-000123", "0000320193-24-000110", "0000320193-24-000081"],
    "filingDate": ["2024-11-01", "2024-10-31", "2024-08-02"],
    "reportDate": ["2024-09-28", "", "2024-06-29"],
    "primaryDocument": ["aapl-20240928.htm", "a8-k.htm", "aapl-20240629.htm"]}}}


def _answers(monkeypatch, mapping):
    def answer(url):
        return OLDER if url.endswith(OLDER_NAME) else mapping[url]

    monkeypatch.setattr(edgar, "read_json", answer)


def test_a_user_agent_without_a_contact_is_refused(monkeypatch):
    monkeypatch.setenv("FETCH_USER_AGENT", "Countercheck/0.1")
    with pytest.raises(FetchError, match="Name contact@domain"):
        edgar.require_contact()


def test_a_cik_is_padded_to_ten_digits():
    assert edgar.pad(320193) == "0000320193"
    assert edgar.pad("CIK0000320193") == "0000320193"
    with pytest.raises(ValueError):
        edgar.pad("none")


def test_ticker_resolves_to_a_padded_cik(monkeypatch):
    _answers(monkeypatch, {edgar.TICKERS: {"0": {"cik_str": 320193, "ticker": "AAPL"}}})
    assert edgar.cik_for("aapl") == "0000320193"
    with pytest.raises(ValueError, match="no CIK"):
        edgar.cik_for("NOSUCH")


def test_filings_are_filtered_by_form_and_carry_a_resolvable_url(monkeypatch):
    _answers(monkeypatch, {edgar.SUBMISSIONS.format(cik="0000320193"): SUBMISSIONS})
    [filing] = edgar.filings("320193", form="10-K", limit=1)
    assert filing.accession == "0000320193-24-000123" and filing.period == "2024-09-28"
    assert filing.url == ("https://www.sec.gov/Archives/edgar/data/320193/"
                          "000032019324000123/aapl-20240928.htm")
    # An 8-K carries no report period, and an empty string is not a period.
    assert edgar.filings("320193", form="8-K", limit=1)[0].period is None


def test_facts_come_back_newest_first_and_an_unknown_tag_is_empty(monkeypatch):
    concept = {"units": {"USD": [{"end": "2023-09-30", "val": 383285000000},
                                 {"end": "2024-09-28", "val": 391035000000}]}}
    _answers(monkeypatch, {edgar.COMPANY_FACTS.format(cik="0000320193"):
                           {"facts": {"us-gaap": {"Revenues": concept}}}})
    values = edgar.facts("320193", "Revenues")
    assert [v["end"] for v in values] == ["2024-09-28", "2023-09-30"]
    assert edgar.facts("320193", "NotATag") == []


OLDER = {"form": ["10-K"], "accessionNumber": ["0000320193-15-000000"],
         "filingDate": ["2015-10-28"], "reportDate": ["2015-09-26"],
         "primaryDocument": ["aapl-20150926.htm"]}


def test_filings_read_the_older_file_only_when_more_are_wanted(monkeypatch):
    seen = []

    def answer(url):
        seen.append(url)
        return OLDER if url.endswith(OLDER_NAME) else SUBMISSIONS

    monkeypatch.setattr(edgar, "read_json", answer)
    # One 10-K is inline, so asking for one must not spend a request on the older file.
    assert len(edgar.filings("320193", form="10-K", limit=1)) == 1
    assert not any(u.endswith(OLDER_NAME) for u in seen)

    seen.clear()
    found = edgar.filings("320193", form="10-K", limit=5)
    assert [f.filed_at for f in found] == ["2024-11-01", "2015-10-28"]
    assert any(u.endswith(OLDER_NAME) for u in seen)
