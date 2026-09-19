"""Keyword index held in memory. Used when Elasticsearch is not configured, and in tests."""
from __future__ import annotations

import re
from datetime import datetime

from backend.models import DocumentSnapshot, SourceSpan


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class MemoryIndex:
    used_embeddings = False  # keyword overlap only

    def __init__(self) -> None:
        self.entries: dict[str, tuple[SourceSpan, DocumentSnapshot]] = {}

    def index(self, document: DocumentSnapshot, spans: list[SourceSpan]) -> None:
        for span in spans:
            self.entries[span.id] = (span, document)

    def search(self, query: str, *, size: int, corpus: list[str] | None = None,
               cutoff: datetime | None = None) -> list[str]:
        wanted = _tokens(query)
        scored = []
        for span, document in self.entries.values():
            if corpus is not None and document.id not in corpus:
                continue
            if cutoff is not None and not (document.admissible_from
                                           and document.admissible_from <= cutoff):
                continue
            overlap = len(wanted & _tokens(span.text))
            if overlap:
                scored.append((-overlap, span.id))
        return [span_id for _, span_id in sorted(scored)[:size]]
