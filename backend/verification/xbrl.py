"""Check a spoken figure against the figure the company filed for the same metric and period.

The mapping from a metric's wording to a tag is a fixed table, never a guess: a metric that is not
in the table, or a tag the company did not file, is reported as not_found. A missing match is a
result, not a failure. Nothing here writes to the ledger.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from backend.ingestion.edgar import facts
from backend.models import AssertionType, Claim, Relationship

AGENT = "xbrl-verifier"
TIER = "structured"
NOT_FOUND, SUPPORTS, CONTRADICTS = "not_found", "supports", "contradicts"

# Wording heard on a call, and the tags a company may file it under, most specific first.
TAGS: dict[str, tuple[str, ...]] = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues",
                "SalesRevenueNet"),
    "net revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"),
    "net income": ("NetIncomeLoss",),
    "net earnings": ("NetIncomeLoss",),
    "operating income": ("OperatingIncomeLoss",),
    "gross profit": ("GrossProfit",),
    "total assets": ("Assets",),
    "earnings per share": ("EarningsPerShareDiluted", "EarningsPerShareBasic"),
    "diluted earnings per share": ("EarningsPerShareDiluted",),
    "research and development": ("ResearchAndDevelopmentExpense",),
    "operating cash flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "quarterly dividend": ("CommonStockDividendsPerShareDeclared",),
}
SCALES = {"thousand": 3, "million": 6, "billion": 9, "trillion": 12}
# Wording that names a measure the company defined itself. It has no filed counterpart, so the
# difference from the filed figure is a disclosure gap to report, never a contradiction.
ADJUSTED = re.compile(r"\b(?:adjusted|non[- ]?gaap|underlying|organic|pro[- ]?forma"
                      r"|normali[sz]ed|excluding|before\s+reimbursements?"
                      r"|constant[- ]currency)", re.I)
# A claim about what will happen has nothing filed to check it against yet.
FORWARD = {AssertionType.future_target, AssertionType.policy_commitment}
# Days a stated period covers, so an annual figure cannot answer a quarterly claim.
SPANS = {"quarter": (60, 120), "year": (300, 400)}
UNITS = {"EarningsPerShareDiluted": "USD/shares", "EarningsPerShareBasic": "USD/shares",
         "CommonStockDividendsPerShareDeclared": "USD/shares"}


@dataclass(frozen=True)
class Check:
    claim_id: str
    stance: str
    agent: str = AGENT
    tier: str = TIER
    tag: str | None = None
    filed: Decimal | None = None
    stated: Decimal | None = None
    period: str | None = None
    accession: str | None = None
    source_url: str | None = None
    relationship: Relationship | None = None
    note: str = ""


def tag_for(metric: str | None) -> tuple[str, ...]:
    """Tags a metric's wording maps to. Unknown wording maps to nothing rather than to a guess."""
    text = (metric or "").lower().strip()
    if not text:
        return ()
    for phrase in sorted(TAGS, key=len, reverse=True):
        if phrase in text:
            return TAGS[phrase]
    return ()


def stated_value(claim: Claim) -> Decimal | None:
    """The number the claim states, scaled once by whichever of the value or unit names a scale.

    A value that names more than one number, such as a percentage change and an amount, does not
    say on its own which one a filed figure should be compared with, so nothing is returned.
    """
    raw = (claim.value or "").strip()
    numbers = re.findall(r"-?\d[\d,]*\.?\d*", raw)
    if not numbers:
        return None
    if len({n.replace(",", "") for n in numbers}) > 1:
        # An amount is written with a currency mark or a scale word; a rate of change is not.
        # When exactly one number is written that way, it is the one a filed figure answers.
        amounts = re.findall(r"[$\u00a3\u20ac]\s*(-?\d[\d,]*\.?\d*)"
                             r"|(-?\d[\d,]*\.?\d*)\s*(?:thousand|million|billion|trillion)",
                             raw, re.I)
        picked = {a or b for a, b in amounts}
        if len(picked) != 1:
            return None
        numbers = [picked.pop()]
    try:
        value = Decimal(numbers[0].replace(",", ""))
    except InvalidOperation:
        return None
    for source in (raw.lower(), (claim.unit or "").lower()):
        for word, power in SCALES.items():
            if word in source:
                return value.scaleb(power)
    return value


def window(period: str | None) -> tuple[str, str] | None:
    """The dates a stated period covers, as the filed facts record them."""
    text = (period or "").strip()
    quarter = re.fullmatch(r"(\d{4})[-\s]?Q([1-4])", text, re.I)
    if quarter:
        year, q = int(quarter.group(1)), int(quarter.group(2))
        ends = {1: ("-01-01", "-04-30"), 2: ("-04-01", "-07-31"),
                3: ("-07-01", "-10-31"), 4: ("-10-01", "-12-31")}[q]
        return f"{year}{ends[0]}", f"{year}{ends[1]}"
    year = re.search(r"(19|20)\d{2}", text)
    if year:
        return f"{year.group()}-01-01", f"{year.group()}-12-31"
    return None


def _tolerance(claim: Claim, stated: Decimal) -> Decimal:
    """Agreement is judged to the precision the speaker used, as stated numbers are rounded."""
    written = re.search(r"-?\d[\d,]*\.?\d*", (claim.value or ""))
    digits = Decimal(written.group().replace(",", "")) if written else stated
    step = Decimal(1).scaleb(int(digits.as_tuple().exponent)) / 2
    return step.scaleb(int(stated.adjusted() - digits.adjusted())) if digits else step


def _duration(row: dict) -> int | None:
    start, end = row.get("start"), row.get("end")
    if not start or not end:
        return None
    from datetime import date
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def verify(claim: Claim, cik: str, period: str | None = None) -> Check:
    """Check the claim against the filed figure for its own period.

    The period must be known. Without it the newest filed value would answer a claim made years
    earlier, so a claim that names no period, and is given none, is reported as not_found.
    """
    if claim.assertion_type in FORWARD:
        return Check(claim.id, NOT_FOUND, note="claim is about a future period")
    wording = f"{claim.metric or ''} {claim.text}"
    if ADJUSTED.search(wording):
        return Check(claim.id, NOT_FOUND,
                     note="claim names a company-defined measure with no filed counterpart")
    tags = tag_for(claim.metric)
    if not tags:
        return Check(claim.id, NOT_FOUND, note="metric wording is not in the tag table")
    stated = stated_value(claim)
    if stated is None:
        return Check(claim.id, NOT_FOUND, note="claim states no number to check")
    stated_period = (claim.period or "").strip() or (period or "").strip()
    span = window(stated_period)
    if span is None:
        return Check(claim.id, NOT_FOUND, note="no period to compare the claim against")
    for tag in tags:
        for row in facts(cik, tag, unit=UNITS.get(tag, "USD")):
            end = row.get("end", "")
            if not (span[0] <= end <= span[1]):
                continue
            length = _duration(row)
            if length is not None:
                wanted = SPANS["quarter"] if re.search(r"q[1-4]", stated_period, re.I) \
                    else SPANS["year"]
                if not wanted[0] <= length <= wanted[1]:
                    continue
            filed = Decimal(str(row["val"]))
            close = abs(filed - stated) <= _tolerance(claim, stated)
            return Check(
                claim.id, SUPPORTS if close else CONTRADICTS, tag=tag, filed=filed,
                stated=stated, period=f"{row.get('start', '')}..{end}".strip("."),
                accession=row.get("accn"),
                source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                relationship=Relationship.supports if close else Relationship.contradicts,
                note=f"filed {filed} against stated {stated}")
    return Check(claim.id, NOT_FOUND, note="company filed no value for this tag and period")
