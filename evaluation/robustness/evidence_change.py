"""Controlled evidence-change checks (specification section 18.4) on the pure components."""
from __future__ import annotations

from backend.evidence.provenance import evidence_hash, reconcile, withdraw
from backend.models import EvidenceItem, InvestigationState


def repeating_adds_nothing(state: InvestigationState, item: EvidenceItem) -> bool:
    """Adding a passage again, or an identical copy from another page, leaves the groups as is."""
    copy = item.model_copy(update={"id": item.id + "-copy", "span_id": item.span_id + "-copy"})
    return not reconcile(state, [item], {}) and not reconcile(state, [copy], {})


def withdrawal_recomputes(state: InvestigationState, evidence_id: str) -> bool:
    """Withdrawing evidence changes the active set, and the item leaves the ledger."""
    before = evidence_hash(state.groups)
    withdraw(state, evidence_id)
    return evidence_hash(state.groups) != before and all(e.id != evidence_id for e in state.evidence)


def order_does_not_matter(make_state, items: list[EvidenceItem]) -> bool:
    forward, backward = make_state(), make_state()
    reconcile(forward, [i.model_copy() for i in items], {})
    reconcile(backward, [i.model_copy() for i in reversed(items)], {})
    return evidence_hash(forward.groups) == evidence_hash(backward.groups)
