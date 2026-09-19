"""Baselines A0 and A1: the same model without the structured investigation."""
from __future__ import annotations

from backend.db import Store
from backend.models import Claim, EvidenceItem, InvestigationState, Relationship
from backend.providers.base import LLM, StateUpdate
from backend.retrieval.search import SearchIndex


def claim_only(llm: LLM, claim: Claim) -> StateUpdate:
    """A0: judge the claim with no retrieved evidence."""
    return llm.update_state(InvestigationState(claim=claim), [], [])


def retrieve_then_judge(llm: LLM, index: SearchIndex, store: Store, claim: Claim,
                        size: int = 8) -> StateUpdate:
    """A1: one search on the claim text, then one judgment over the retrieved passages."""
    state = InvestigationState(claim=claim)
    for i, span_id in enumerate(index.search(claim.text, size=size)):
        span = store.get("spans", span_id)
        if span:
            state.evidence.append(EvidenceItem(
                id=f"{claim.id}-b{i}", claim_id=claim.id, span_id=span_id,
                document_id=span["document_id"], quote=span["text"],
                relationship=Relationship.context, target="claim"))
    return llm.update_state(state, [e.id for e in state.evidence], [])
