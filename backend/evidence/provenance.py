"""Group evidence by the original observation it comes from, so repetition is counted once."""
from __future__ import annotations

import hashlib
import re

from backend.models import EvidenceGroup, EvidenceItem, EvidenceOrigin, InvestigationState


def _family_key(quote: str) -> str:
    normalized = re.sub(r"\W+", " ", quote.lower()).strip()
    return "grp-" + hashlib.sha256(normalized.encode()).hexdigest()[:12]


def evidence_hash(groups: list[EvidenceGroup]) -> str:
    active = sorted(f"{g.id}:{g.version}" for g in groups if g.active)
    return hashlib.sha256("|".join(active).encode()).hexdigest()[:16]


def reconcile(state: InvestigationState, items: list[EvidenceItem],
              repeats: dict[str, str]) -> bool:
    """Add items to the state. `repeats` maps a span id to the span id it repeats.

    Return True when the set of active groups changed. Identical text and declared
    repetitions join an existing group, so they add no new observation.
    """
    before = evidence_hash(state.groups)
    groups = {g.id: g for g in state.groups}
    by_span = {e.span_id: e for e in state.evidence}
    known = {(e.span_id, e.target) for e in state.evidence}
    # Originals are processed before the passages that repeat them, whatever order they arrive in.
    for item in sorted(items, key=lambda i: i.span_id in repeats):
        if (item.span_id, item.target) in known:
            continue
        original = by_span.get(repeats.get(item.span_id, ""))
        if original is not None and original.group_id:
            item.group_id = original.group_id
            item.origin = EvidenceOrigin.third_party_repetition
        else:
            item.group_id = _family_key(item.quote)
        group = groups.setdefault(item.group_id, EvidenceGroup(id=item.group_id, member_ids=[]))
        group.member_ids.append(item.id)
        state.evidence.append(item)
        by_span[item.span_id] = item
        known.add((item.span_id, item.target))
    state.groups = list(groups.values())
    return evidence_hash(state.groups) != before


def withdraw(state: InvestigationState, evidence_id: str) -> None:
    """Remove an item from the active ledger. Stored history is kept by the caller."""
    state.evidence = [e for e in state.evidence if e.id != evidence_id]
    for group in state.groups:
        if evidence_id in group.member_ids:
            group.member_ids.remove(evidence_id)
            group.version += 1
            group.active = bool(group.member_ids)


def lineage(state: InvestigationState, span_ids: list[str]) -> list[str]:
    """Provenance groups of the passages a calculation reads its inputs from."""
    groups = {e.group_id for e in state.evidence if e.span_id in span_ids and e.group_id}
    return sorted(groups)
