"""Retrieve passages for verification questions and attach their neighbouring context."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.config import Retrieval
from backend.db import Store
from backend.models import Claim, DocumentSnapshot, SourceSpan, VerificationQuestion
from backend.retrieval.rrf import fuse


class SearchIndex(Protocol):
    def index(self, document: DocumentSnapshot, spans: list[SourceSpan]) -> None: ...
    def search(self, query: str, *, size: int, corpus: list[str] | None = None,
               cutoff: datetime | None = None) -> list[str]: ...


def retrieve(index: SearchIndex, store: Store, claim: Claim,
             questions: list[VerificationQuestion], settings: Retrieval,
             corpus: list[str] | None = None,
             cutoff: datetime | None = None) -> tuple[list[SourceSpan], list[SourceSpan]]:
    """Return (retrieved passages, neighbouring context passages)."""
    exact = " ".join(filter(None, [claim.subject, claim.metric, claim.period, claim.unit]))
    hits: list[str] = []
    for question in questions:
        rankings = [index.search(f"{question.text} {question.evidence_needed}",
                                 size=settings.candidates_per_query, corpus=corpus, cutoff=cutoff)]
        if exact:
            rankings.append(index.search(exact, size=settings.candidates_per_query,
                                         corpus=corpus, cutoff=cutoff))
        hits += fuse(rankings)[:settings.retained_passages_per_question]
    hit_ids = list(dict.fromkeys(hits))
    passages = [s for s in (store.get("spans", i, SourceSpan) for i in hit_ids) if s]
    context: dict[str, SourceSpan] = {}
    if settings.preserve_critical_context:
        for span in passages:
            for neighbour in (span.prev_id, span.next_id, *span.note_ids):
                if neighbour and neighbour not in hit_ids and neighbour not in context:
                    found = store.get("spans", neighbour, SourceSpan)
                    if found:
                        context[neighbour] = found
    return passages, list(context.values())
