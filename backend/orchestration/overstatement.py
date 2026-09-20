"""Assemble one row per claim from the call, the filing and the agents that read them.

Nothing here fetches or parses. It takes the call, the filing's items and the company's filed
figures as they already are, runs each agent over every claim, and records what each one found
together with where it found it. A row keeps both measures apart and says when it abstained.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Callable

from backend.assessment.inflation import Axes, assess
from backend.claims.features import puffery_density, specificity, specificity_score
from backend.claims.lexicon import LexiconMissing, hedging_delta
from backend.ingestion.sections import Section
from backend.models import Claim
from backend.retrieval import risk_matcher
from backend.verification import xbrl

ABSTAIN, CONTRADICTED, CONSISTENT = "abstain", "contradicted", "consistent"
# Above this share of what was found disagreeing, the row is reported as contradicted.
DISAGREEMENT = 0.5


@dataclass(frozen=True)
class Row:
    claim_id: str
    claim: str
    speaker: str | None
    segment: str
    claim_type: str
    specificity: int
    specificity_axes: dict[str, bool]
    puffery_per_100w: float
    rhetorical_inflation: float
    evidence_gap: float | None
    verdict: str
    evidence: list[dict] = field(default_factory=list)
    parts: dict[str, float] = field(default_factory=dict)
    note: str = ""


def _verdict(axes: Axes) -> str:
    if axes.abstained or axes.evidence_gap is None:
        return ABSTAIN
    return CONTRADICTED if axes.evidence_gap >= DISAGREEMENT else CONSISTENT


def row_for(claim: Claim, *, speaker: str | None, segment: str, cik: str,
            sections: dict[str, Section], accession: str | None = None,
            source_url: str | None = None,
            embed: Callable[[list[str]], list[list[float]]] | None = None) -> Row:
    check = xbrl.verify(claim, cik)
    matches = risk_matcher.match(claim, sections, accession=accession, source_url=source_url,
                                 embed=embed, k=3)
    evidence = [{"agent": check.agent, "tier": check.tier, "stance": check.stance,
                 "tag": check.tag, "filed": str(check.filed) if check.filed is not None else None,
                 "stated": str(check.stated) if check.stated is not None else None,
                 "accession": check.accession, "source_url": check.source_url,
                 "note": check.note}]
    evidence += [{"agent": m.agent, "tier": m.tier, "stance": "neutral", "item": m.item,
                  "quote": m.quote, "score": m.score, "method": m.method,
                  "accession": m.accession, "source_url": m.source_url} for m in matches]

    hedging = None
    if matches:
        try:
            hedging = hedging_delta(claim.text, matches[0].quote)
        except LexiconMissing:
            hedging = None
    axes = assess(claim, [check.stance], hedging)
    return Row(
        claim_id=claim.id, claim=claim.text, speaker=speaker, segment=segment,
        claim_type=str(claim.assertion_type), specificity=specificity_score(claim),
        specificity_axes=specificity(claim),
        puffery_per_100w=round(puffery_density(claim.text), 2),
        rhetorical_inflation=axes.rhetorical_inflation, evidence_gap=axes.evidence_gap,
        verdict=_verdict(axes), evidence=evidence, parts=axes.parts,
        note=axes.reason or ("no filing passage was close to the claim" if not matches else ""))


def as_dicts(rows: list[Row]) -> list[dict]:
    return [asdict(r) for r in rows]
