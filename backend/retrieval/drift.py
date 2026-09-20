"""Follow a commitment from one filing to the next and report how its wording changed.

A commitment can weaken without being withdrawn: the same point is still made, but with fewer
words that bind and more that qualify. This compares a passage with its closest counterpart in
the earlier filing and reports the change in how firmly it is put. A commitment that has no
counterpart in the later filing is reported as dropped, which is a fact about the two documents
and not a judgement about why.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.claims.lexicon import DICTIONARY, LexiconMissing, densities
from backend.models import SourceSpan
from backend.retrieval.novelty import SAME, similarity

AGENT = "drift-tracker"
TIER = "filing_text"
WEAKENED, FIRMER, UNCHANGED, DROPPED, NOT_FOUND = (
    "weakened", "firmer", "unchanged", "dropped", "not_found")
# A change in strong-modal density smaller than this is treated as the same wording.
NOTICEABLE = 0.5


@dataclass(frozen=True)
class Drift:
    span_id: str
    status: str
    quote: str
    prior_quote: str | None = None
    prior_span_id: str | None = None
    similarity: float = 0.0
    strength_change: float | None = None
    agent: str = AGENT
    tier: str = TIER
    note: str = ""


def _strength(text: str, path=DICTIONARY) -> float | None:
    try:
        found = densities(text, path)
    except LexiconMissing:
        return None
    return found["Strong_Modal"] - found["Weak_Modal"]


def follow(current: SourceSpan, prior: list[SourceSpan], *, same: float = SAME,
           path=DICTIONARY) -> Drift:
    """The earlier passage making the same point, and how the wording moved."""
    best, best_span = 0.0, None
    for span in prior:
        score = similarity(current.text, span.text)
        if score > best:
            best, best_span = score, span
    if best_span is None or best < same:
        return Drift(current.id, NOT_FOUND, current.text, similarity=round(best, 4),
                     note="no earlier passage makes the same point")
    now, before = _strength(current.text, path), _strength(best_span.text, path)
    if now is None or before is None:
        status, change = UNCHANGED, None
        note = "the dictionary is missing, so only the pairing is reported"
    else:
        change = round(now - before, 4)
        note = ""
        if change <= -NOTICEABLE:
            status = WEAKENED
        elif change >= NOTICEABLE:
            status = FIRMER
        else:
            status = UNCHANGED
    return Drift(current.id, status, current.text, prior_quote=best_span.text,
                 prior_span_id=best_span.id, similarity=round(best, 4),
                 strength_change=change, note=note)


def dropped(current: list[SourceSpan], prior: list[SourceSpan], *, same: float = SAME
            ) -> list[Drift]:
    """Earlier passages with no counterpart in the later filing."""
    out = []
    for span in prior:
        best = max((similarity(span.text, other.text) for other in current), default=0.0)
        if best < same:
            out.append(Drift(span.id, DROPPED, span.text, similarity=round(best, 4),
                             note="the later filing makes no comparable statement"))
    return out
