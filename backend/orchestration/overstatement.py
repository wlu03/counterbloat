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
from backend.retrieval import drift, novelty, risk_matcher
from backend.verification import outcomes, xbrl

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


def _verdict(axes: Axes, stances: list[str]) -> str:
    """A claim is contradicted only when an agent that looked at something disagreed with it.

    A hedging delta still counts towards the gap, because the filing putting the same point more
    carefully is worth reading, but a difference in wording is not a disagreement about fact.
    """
    if axes.abstained or axes.evidence_gap is None:
        return ABSTAIN
    if xbrl.CONTRADICTS not in stances:
        return CONSISTENT
    return CONTRADICTED if axes.evidence_gap >= DISAGREEMENT else CONSISTENT


def row_for(claim: Claim, *, speaker: str | None, segment: str, cik: str,
            sections: dict[str, Section], period: str | None = None,
            accession: str | None = None, source_url: str | None = None,
            turn: str | None = None, call_date: str | None = None,
            prior: dict[str, Section] | None = None,
            embed: Callable[[list[str]], list[list[float]]] | None = None) -> Row:
    """One row for one claim.

    `turn` is the speaker's whole turn, used only for the word-category measures. A single
    sentence holds too few words for the modal lists to register, so the delta taken over one
    sentence is almost always zero and says nothing.
    """
    check = xbrl.verify(claim, cik, period)
    # Almost all of a risk factor section is carried over, and wording that was already
    # there cannot be the filing answering a claim made this quarter.
    only = None
    if prior is not None:
        current_spans = [span for _, span in risk_matcher.candidates(sections)]
        prior_spans = [span for _, span in risk_matcher.candidates(prior)]
        only = {n.span_id for n in novelty.added(current_spans, prior_spans)}
    matches = risk_matcher.match(claim, sections, accession=accession,
                                 source_url=source_url, embed=embed, k=3,
                                 only=only)
    evidence = [{"agent": check.agent, "tier": check.tier, "stance": check.stance,
                 "tag": check.tag, "filed": str(check.filed) if check.filed is not None else None,
                 "stated": str(check.stated) if check.stated is not None else None,
                 "accession": check.accession, "source_url": check.source_url,
                 "note": check.note}]
    evidence += [{"agent": m.agent, "tier": m.tier, "stance": "neutral", "item": m.item,
                  "quote": m.quote, "score": m.score, "method": m.method,
                  "accession": m.accession, "source_url": m.source_url} for m in matches]

    if call_date:
        later = outcomes.check(claim.id, cik, call_date)
        if later.stance != outcomes.NOT_FOUND:
            evidence.append({"agent": later.agent, "tier": later.tier,
                             "stance": later.stance, "item": later.item,
                             "filed_at": later.filed_at,
                             "months_after": later.months_after,
                             "accession": later.accession, "note": later.note})

    if prior is not None and matches:
        moved = drift.follow(next(sp for _, sp in risk_matcher.candidates(sections)
                                  if sp.id == matches[0].span_id),
                             [sp for _, sp in risk_matcher.candidates(prior)])
        if moved.status != drift.NOT_FOUND:
            evidence.append({"agent": moved.agent, "tier": moved.tier,
                             "stance": "context", "status": moved.status,
                             "strength_change": moved.strength_change,
                             "prior_quote": moved.prior_quote,
                             "similarity": moved.similarity})

    hedging = None
    if matches:
        try:
            hedging = hedging_delta(turn or claim.text, matches[0].quote)
        except LexiconMissing:
            hedging = None
    axes = assess(claim, [check.stance], hedging)
    return Row(
        claim_id=claim.id, claim=claim.text, speaker=speaker, segment=segment,
        claim_type=str(claim.assertion_type), specificity=specificity_score(claim),
        specificity_axes=specificity(claim),
        puffery_per_100w=round(puffery_density(claim.text), 2),
        rhetorical_inflation=axes.rhetorical_inflation, evidence_gap=axes.evidence_gap,
        verdict=_verdict(axes, [check.stance]), evidence=evidence, parts=axes.parts,
        note=axes.reason or ("no filing passage was close to the claim" if not matches else ""))


def as_dicts(rows: list[Row]) -> list[dict]:
    return [asdict(r) for r in rows]
