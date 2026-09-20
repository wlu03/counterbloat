"""Find the passages of an annual report that answer a claim made on the call.

The agent reads the risk factors and the management discussion of the filing for the same period
and returns the passages closest to the claim. It scores nothing and decides nothing: a match is
a pointer to text, and what the text means is judged later. Embeddings are used when a model is
configured, and word overlap otherwise, and every match says which was used.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

from backend.ingestion.sections import MD_AND_A, RISK_FACTORS, Section
from backend.models import Claim

AGENT = "risk-matcher"
TIER = "filing_text"
EMBEDDING, KEYWORD = "embedding", "keyword"
READ = (RISK_FACTORS, MD_AND_A)


@dataclass(frozen=True)
class Match:
    claim_id: str
    item: str
    span_id: str
    quote: str
    score: float
    method: str
    accession: str | None = None
    source_url: str | None = None
    agent: str = AGENT
    tier: str = TIER


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", text.lower()))


def _overlap(query: set[str], passage: str) -> float:
    other = _tokens(passage)
    if not query or not other:
        return 0.0
    return len(query & other) / math.sqrt(len(query) * len(other))


def _cosine(a: list[float], b: list[float]) -> float:
    top = sum(x * y for x, y in zip(a, b))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return top / size if size else 0.0


def candidates(sections: dict[str, Section], items=READ, min_words: int = 12):
    """Passages worth comparing: long enough to say something, from the items that discuss risk.

    An item the filer answered by pointing at another document is skipped, because matching
    nothing there would look like the filing having nothing to say.
    """
    for item in items:
        section = sections.get(item)
        if section is None or section.incorporated_by_reference:
            continue
        for span in section.spans:
            if len(span.text.split()) >= min_words:
                yield item, span


def match(claim: Claim, sections: dict[str, Section], *, accession: str | None = None,
          source_url: str | None = None, embed: Callable[[list[str]], list[list[float]]] | None = None,
          k: int = 5, items=READ, only: set[str] | None = None) -> list[Match]:
    """The k passages closest to the claim, best first. An empty list means nothing was close.

    `only` limits the search to particular passages, such as the ones the filing added this year.
    Almost all of a risk factor section is carried over from the previous filing, and wording that
    was already there before the claim was made cannot be the filing answering that claim.
    """
    found = [(item, span) for item, span in candidates(sections, items)
             if only is None or span.id in only]
    if not found:
        return []
    vectors: list[list[float]] = []
    if embed is not None:
        vectors = embed([claim.text] + [span.text for _, span in found])
    if vectors and len(vectors) == len(found) + 1:
        scores = [_cosine(vectors[0], v) for v in vectors[1:]]
        method = EMBEDDING
    else:
        query = _tokens(f"{claim.text} {claim.metric or ''} {claim.subject or ''}")
        scores = [_overlap(query, span.text) for _, span in found]
        method = KEYWORD
    ranked = sorted(zip(scores, range(len(found))), key=lambda pair: (-pair[0], pair[1]))
    out = []
    for score, place in ranked[:k]:
        if score <= 0:
            break
        item, span = found[place]
        out.append(Match(claim_id=claim.id, item=item, span_id=span.id, quote=span.text,
                         score=round(float(score), 4), method=method,
                         accession=accession, source_url=source_url))
    return out
