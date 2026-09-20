"""Baselines A0 and A1: the same model without the structured investigation."""
from __future__ import annotations

from backend.db import Store
from backend.models import Claim, EvidenceItem, InvestigationState, Relationship
from backend.providers.base import LLM, StateUpdate
from backend.retrieval.search import SearchIndex


def claim_only(llm: LLM, claim: Claim, task: str = "") -> StateUpdate:
    """A0: judge the claim with no retrieved evidence."""
    return llm.update_state(InvestigationState(claim=claim, task=task), [], [])


def retrieve_then_judge(llm: LLM, index: SearchIndex, store: Store, claim: Claim,
                        size: int = 8, task: str = "") -> StateUpdate:
    """A1: one search on the claim text, then one judgment over the retrieved passages.

    `task` is the decision protocol the pipeline is given. Both arms are told the same one, or
    the comparison measures the protocol rather than the structure.
    """
    state = InvestigationState(claim=claim, task=task)
    for i, span_id in enumerate(index.search(claim.text, size=size)):
        span = store.get("spans", span_id)
        if span:
            state.evidence.append(EvidenceItem(
                id=f"{claim.id}-b{i}", claim_id=claim.id, span_id=span_id,
                document_id=span["document_id"], quote=span["text"],
                relationship=Relationship.context, target="claim"))
    return llm.update_state(state, [e.id for e in state.evidence], [])
