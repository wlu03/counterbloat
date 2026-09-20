"""Retrieve passages for verification questions and attach their neighbouring context."""
from __future__ import annotations

from datetime import datetime
from typing import Protocol

from backend.config import Retrieval
from backend.db import Store
from backend.models import Claim, DocumentSnapshot, RunManifest, SourceSpan, VerificationQuestion
from backend.retrieval.rrf import fuse


class SearchIndex(Protocol):
    def index(self, document: DocumentSnapshot, spans: list[SourceSpan]) -> None: ...
    def search(self, query: str, *, size: int, corpus: list[str] | None = None,
               cutoff: datetime | None = None) -> list[str]: ...


def retrieve(index: SearchIndex, store: Store, claim: Claim,
             questions: list[VerificationQuestion], settings: Retrieval,
             corpus: list[str] | None = None, cutoff: datetime | None = None,
             manifest: RunManifest | None = None) -> tuple[list[SourceSpan], list[SourceSpan]]:
    """Return (retrieved passages, neighbouring context passages)."""
    def search(query: str) -> list[str]:
        found = index.search(query, size=settings.candidates_per_query, corpus=corpus, cutoff=cutoff)
        used = getattr(index, "used_embeddings", None)
        if manifest is not None and used is not None:
            # True only while every search of the analysis has used vectors.
            manifest.embedding_search = used and manifest.embedding_search is not False
        return found

    if corpus is not None and settings.show_whole_corpus_under:
        whole = [s for document in corpus
                 for s in store.find("spans", SourceSpan, document_id=document)]
        if 0 < len(whole) <= settings.show_whole_corpus_under:
            return whole, []

    exact = " ".join(filter(None, [claim.subject, claim.metric, claim.period, claim.unit]))
    # The claim's own wording is the best single query for it, and it is the one query that does
    # not depend on a question the planner happened to write.
    hits: list[str] = search(claim.text)[:settings.retained_passages_per_question]
    for question in questions:
        rankings = [search(f"{question.text} {question.evidence_needed}")]
        if exact:
            rankings.append(search(exact))
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
