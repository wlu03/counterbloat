"""Find the risk factors a filing added, by comparing it with the same company's previous one.

Most of a risk factor section is carried over word for word from year to year. Matching a claim
against carried-over wording says nothing, because the same sentence was there before the claim
was made. A passage counts as added only when no passage in the earlier filing says close to the
same thing, measured by how much vocabulary the two share.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.models import SourceSpan

AGENT = "novelty-checker"
TIER = "peer_comparison"
ADDED, CARRIED_OVER = "added", "carried_over"
# Two passages sharing this much of their vocabulary are treated as the same passage reworded.
SAME = 0.6


@dataclass(frozen=True)
class Novelty:
    span_id: str
    status: str
    quote: str
    closest: float
    closest_span_id: str | None = None
    agent: str = AGENT
    tier: str = TIER


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]{4,}", text.lower()))


def similarity(a: str, b: str) -> float:
    """Share of the shorter passage's vocabulary that the longer one also uses."""
    first, second = _words(a), _words(b)
    if not first or not second:
        return 0.0
    return len(first & second) / min(len(first), len(second))


def compare(current: list[SourceSpan], prior: list[SourceSpan], *, same: float = SAME
            ) -> list[Novelty]:
    """Each current passage marked as added or carried over, with its closest earlier match."""
    earlier = [(span.id, _words(span.text)) for span in prior]
    out = []
    for span in current:
        words = _words(span.text)
        best, best_id = 0.0, None
        for other_id, other in earlier:
            if not words or not other:
                continue
            score = len(words & other) / min(len(words), len(other))
            if score > best:
                best, best_id = score, other_id
        out.append(Novelty(span_id=span.id, quote=span.text,
                           status=CARRIED_OVER if best >= same else ADDED,
                           closest=round(best, 4), closest_span_id=best_id))
    return out


def added(current: list[SourceSpan], prior: list[SourceSpan], *, same: float = SAME
          ) -> list[Novelty]:
    """Only the passages with no close counterpart in the earlier filing."""
    return [n for n in compare(current, prior, same=same) if n.status == ADDED]
