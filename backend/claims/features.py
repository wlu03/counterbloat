"""Measures taken from a claim's own wording. No model runs here and every number is countable.

Specificity counts what a claim gives a reader to check it against. Puffery counts the words that
assert quality without stating anything checkable. The two are reported separately: a vague claim
is not a false one, and a superlative is not a misstatement.
"""
from __future__ import annotations

import re

from backend.models import Claim

DIGIT = re.compile(r"\d")
# A period the speaker named, rather than the filing period the record carries.
DATE = re.compile(r"\b(19|20)\d{2}\b|\bq[1-4]\b|\bfirst|second|third|fourth\s+quarter\b"
                  r"|\bfiscal\b|\bthis (?:quarter|year)\b|\bnext (?:quarter|year)\b", re.I)
# A point of comparison the claim is measured against.
BASELINE = re.compile(r"\b(?:versus|vs\.?|compared (?:to|with)|against|up from|down from"
                      r"|year[- ]over[- ]year|sequentially|prior year|last year|a year ago"
                      r"|same period)\b", re.I)
# Someone outside the company said it, which a reader could go and check.
VERIFIER = re.compile(r"\b(?:certified|audited|verified|validated|ranked|rated|accredited)\s+by\b"
                      r"|\baccording to\b|\bas reported by\b|\bindependently\b", re.I)
# Words that assert quality without saying what was measured.
PUFFERY = {
    "amazing", "best", "best-in-class", "brilliant", "compelling", "cutting-edge",
    "exceptional", "excellent", "extraordinary", "fantastic", "flawless", "incredible",
    "industry-leading", "leading", "marquee", "outstanding", "phenomenal", "premier",
    "remarkable", "spectacular", "state-of-the-art", "superb", "superior", "terrific",
    "tremendous", "unmatched", "unparalleled", "unprecedented", "world-class",
}
SUPERLATIVE = re.compile(r"\b(?:most|best|greatest|largest|strongest|highest|fastest)\b"
                         r"|\b\w{4,}est\b", re.I)
AXES = ("number", "unit", "date", "baseline", "metric", "verifier")


def specificity(claim: Claim) -> dict[str, bool]:
    """Which of the six checkable things the claim states. Absence is vagueness, not falsehood."""
    stated = f"{claim.value or ''} {claim.text}"
    return {
        "number": bool(DIGIT.search(stated)),
        "unit": bool((claim.unit or "").strip()),
        "date": bool((claim.period or "").strip()) or bool(DATE.search(claim.text)),
        "baseline": bool((claim.denominator or "").strip())
                    or bool((claim.population or "").strip())
                    or bool(BASELINE.search(claim.text)),
        "metric": bool((claim.metric or "").strip()),
        "verifier": bool(VERIFIER.search(claim.text)),
    }


def specificity_score(claim: Claim) -> int:
    return sum(specificity(claim).values())


def words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z-]*", text)


def puffery_density(text: str) -> float:
    """Puffery words per hundred words. Zero for wording that states something measurable."""
    found = words(text)
    if not found:
        return 0.0
    hits = sum(1 for w in found if w.lower() in PUFFERY or SUPERLATIVE.fullmatch(w))
    return 100.0 * hits / len(found)
