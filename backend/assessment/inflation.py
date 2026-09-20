"""Two separate measures of a claim, kept apart on purpose.

Rhetorical inflation is how loudly a claim is put: how little it states that could be checked, and
how much of its wording asserts quality. Evidence gap is whether anything found actually
disagrees with it. A loud claim with nothing against it is not a false one, and collapsing the two
into a single grade would say it was.

Both are fractions between zero and one built from named parts with equal weight. The weights are
untuned; nothing here is fitted to an outcome, so a score ranks claims for reading order, not for
how likely a claim is to be wrong.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from backend.claims.features import puffery_density, specificity_score
from backend.models import AssertionType, Claim

FORWARD = {AssertionType.future_target, AssertionType.policy_commitment,
           AssertionType.promotional}
# Puffery at or above this share of words counts as fully inflated wording.
PUFFERY_FULL = 5.0
SUPPORTS, CONTRADICTS, NOT_FOUND = "supports", "contradicts", "not_found"


@dataclass(frozen=True)
class Axes:
    claim_id: str
    rhetorical_inflation: float
    evidence_gap: float | None
    parts: dict[str, float] = field(default_factory=dict)
    checked: int = 0
    abstained: bool = False
    reason: str = ""


def rhetorical_inflation(claim: Claim) -> tuple[float, dict[str, float]]:
    parts = {
        "vagueness": 1.0 - specificity_score(claim) / 6.0,
        "puffery": min(puffery_density(claim.text) / PUFFERY_FULL, 1.0),
        "forward_looking": 1.0 if claim.assertion_type in FORWARD else 0.0,
    }
    return sum(parts.values()) / len(parts), parts


def evidence_gap(stances: list[str], hedging: float | None = None
                 ) -> tuple[float | None, dict[str, float], int]:
    """How much of what was found disagrees with the claim.

    Only a stance that actually looked at something counts. When every agent returned not_found
    there is nothing to divide by, and the answer is None rather than zero, because no evidence
    against a claim is not evidence for it.
    """
    # Only a stance that took a side divides the measure. An agent that looked and found a
    # passage bearing neither way has said nothing about whether the claim holds, and counting it
    # as if it did would dilute a contradiction with the mere fact that someone searched.
    looked = [s for s in stances if s in (SUPPORTS, CONTRADICTS)]
    parts: dict[str, float] = {}
    if looked:
        parts["contradicted_share"] = sum(1 for s in looked if s == CONTRADICTS) / len(looked)
    if hedging is not None and hedging > 0:
        # The claim leans on firm wording where the filing hedges. Capped so one part cannot
        # carry the whole measure.
        parts["hedging_delta"] = min(hedging / 5.0, 1.0)
    if not parts:
        return None, {}, len(looked)
    return sum(parts.values()) / len(parts), parts, len(looked)


def assess(claim: Claim, stances: list[str], hedging: float | None = None) -> Axes:
    loud, loud_parts = rhetorical_inflation(claim)
    gap, gap_parts, checked = evidence_gap(stances, hedging)
    parts = {f"inflation.{k}": v for k, v in loud_parts.items()}
    parts.update({f"gap.{k}": v for k, v in gap_parts.items()})
    if gap is None:
        return Axes(claim.id, round(loud, 4), None, parts, checked, True,
                    "no agent found anything to compare the claim against")
    return Axes(claim.id, round(loud, 4), round(gap, 4), parts, checked)
