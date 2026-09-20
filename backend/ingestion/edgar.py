"""Read-only EDGAR reader: ticker to CIK, a company's filings, and the XBRL facts it filed.

EDGAR has no API key. It refuses requests whose User-Agent does not name a contact address, and
asks callers to stay under ten requests a second. Set FETCH_USER_AGENT to SEC's form,
"Name contact@domain", before calling anything here.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

from backend.config import env
from backend.ingestion.fetch import FetchError, fetch

TICKERS = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
COMPANY_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
OLDER = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{number}/{folder}/{document}"
MIN_SECONDS_BETWEEN_REQUESTS = 0.1

_last_request = 0.0


@dataclass(frozen=True)
class Filing:
    cik: str
    form: str
    accession: str
    filed_at: str
    period: str | None
    primary_document: str
    url: str


def require_contact() -> str:
    """EDGAR answers 403 unless the User-Agent names a contact address."""
    agent = env("FETCH_USER_AGENT", "")
    if "@" not in agent:
        raise FetchError(
            "EDGAR needs FETCH_USER_AGENT in SEC's form, \"Name contact@domain\"")
    return agent


def pad(cik: str | int) -> str:
    """EDGAR returns 404 or 500 for a CIK that is not padded to ten digits."""
    digits = re.sub(r"\D", "", str(cik))
    if not digits:
        raise ValueError(f"not a CIK: {cik!r}")
    return digits.zfill(10)


def read_json(url: str, attempts: int = 3) -> dict:
    """Read one JSON document, pausing between requests and retrying a dropped connection.

    A sweep over many companies is thousands of requests, and a connection that times out part
    way through should not end it. A refusal such as 403 or 404 is not retried.
    """
    global _last_request
    require_contact()
    for attempt in range(1, attempts + 1):
        wait = MIN_SECONDS_BETWEEN_REQUESTS - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            content, _, _ = fetch(url, ("application/json",))
        except FetchError as exc:
            _last_request = time.monotonic()
            if attempt == attempts or "returned" in str(exc):
                raise
            time.sleep(attempt)
            continue
        _last_request = time.monotonic()
        return json.loads(content)
    raise FetchError(f"cannot read {url}")


def cik_for(ticker: str) -> str:
    rows = read_json(TICKERS)
    wanted = ticker.strip().upper()
    for row in rows.values():
        if row["ticker"].upper() == wanted:
            return pad(row["cik_str"])
    raise ValueError(f"no CIK for ticker {ticker!r}")


def _rows(cik: str, block: dict, form: str | None) -> list[Filing]:
    found = []
    for i, value in enumerate(block["form"]):
        if form is not None and value != form:
            continue
        accession = block["accessionNumber"][i]
        document = block["primaryDocument"][i]
        found.append(Filing(
            cik=cik, form=value, accession=accession,
            filed_at=block["filingDate"][i], period=block["reportDate"][i] or None,
            primary_document=document,
            url=ARCHIVE.format(number=int(cik), folder=accession.replace("-", ""),
                               document=document)))
    return found


def filings(cik: str, form: str | None = None, limit: int = 10) -> list[Filing]:
    """Filings newest first, optionally one form such as 10-K or 8-K.

    A company with a long history has about a thousand filings inline and the rest in further
    files that the submissions response names. Those are read only when the inline block has not
    already produced enough, because each one is another request.
    """
    cik = pad(cik)
    submissions = read_json(SUBMISSIONS.format(cik=cik))["filings"]
    found = _rows(cik, submissions["recent"], form)
    for older in submissions.get("files", []):
        if len(found) >= limit:
            break
        found.extend(_rows(cik, read_json(OLDER.format(name=older["name"])), form))
    return found[:limit]


def facts(cik: str, tag: str, taxonomy: str = "us-gaap", unit: str = "USD") -> list[dict]:
    """Every value the company filed for one XBRL tag, newest period first.

    Each entry keeps the accession and the period so a claim can be tied to the filed figure
    rather than to a number a model produced.
    """
    data = read_json(COMPANY_FACTS.format(cik=pad(cik)))
    concept = data.get("facts", {}).get(taxonomy, {}).get(tag)
    if concept is None:
        return []
    values = concept.get("units", {}).get(unit, [])
    return sorted(values, key=lambda v: v.get("end", ""), reverse=True)
