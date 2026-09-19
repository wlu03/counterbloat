"""Anchors locate a quote in a document's normalized text and can be checked later."""
from __future__ import annotations

from pydantic import BaseModel

CONTEXT = 32


class Anchor(BaseModel):
    span_id: str
    exact: str
    prefix: str
    suffix: str
    start: int
    end: int


def make_anchor(span_id: str, text: str, start: int, end: int) -> Anchor:
    return Anchor(span_id=span_id, exact=text[start:end], prefix=text[max(0, start - CONTEXT):start],
                  suffix=text[end:end + CONTEXT], start=start, end=end)


def resolve(anchor: Anchor, text: str) -> tuple[int, int] | None:
    """Return the quote's offsets in `text`, or None when the quote is no longer there."""
    if text[anchor.start:anchor.end] == anchor.exact:
        return anchor.start, anchor.end
    # Offsets moved. Find the quote again using its surrounding text.
    position = text.find(anchor.prefix + anchor.exact + anchor.suffix)
    if position >= 0:
        start = position + len(anchor.prefix)
        return start, start + len(anchor.exact)
    if text.count(anchor.exact) == 1:
        start = text.index(anchor.exact)
        return start, start + len(anchor.exact)
    return None
