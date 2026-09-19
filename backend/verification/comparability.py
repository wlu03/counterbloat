"""Compare what a claim asserts with what a piece of evidence measures."""
from __future__ import annotations

import re

FIELDS = ("metric", "unit", "denominator", "population", "boundary", "period")


def _norm(value: str | None) -> str | None:
    return re.sub(r"\s+", " ", value.lower()).strip() if value else None


def differences(claim_fields: dict, evidence_fields: dict) -> list[str]:
    """Return the fields that both sides state and that do not match.

    A field stated on only one side is not a difference. It is a question still to be answered.
    The denominator is the exception: a per-unit measure against a total is a real mismatch.
    """
    found = []
    for field in FIELDS:
        a, b = _norm(claim_fields.get(field)), _norm(evidence_fields.get(field))
        if field == "denominator":
            if a != b and (a or b):
                found.append(field)
        elif a and b and a != b:
            found.append(field)
    return found
