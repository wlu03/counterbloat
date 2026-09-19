"""Group evidence by the original observation it comes from, so repetition is counted once."""
from __future__ import annotations

import hashlib
import re

from backend.models import (
    AnswerStatus, EvidenceGroup, EvidenceItem, EvidenceOrigin, InvestigationState,
)


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
    by_span: dict[str, EvidenceItem] = {}

    def note(item: EvidenceItem) -> None:
        # The original of a span is its first item about the claim, else its first item.
        held = by_span.get(item.span_id)
        if held is None or (item.target == "claim" and held.target != "claim"):
            by_span[item.span_id] = item

    for existing in state.evidence:
        note(existing)
    # An identical passage joins the group its twin is in, which may be a declared original's.
    by_text = {_family_key(e.quote): e.group_id for e in state.evidence if e.group_id}
    known = {(e.span_id, e.target) for e in state.evidence}
    # Originals are processed before the passages that repeat them, whatever order they arrive in.
    for item in sorted(items, key=lambda i: i.span_id in repeats):
        if (item.span_id, item.target) in known:
            continue
        item.repeats_span_id = repeats.get(item.span_id)
        original = by_span.get(item.repeats_span_id or "")
        if original is not None and original.group_id:
            item.group_id = original.group_id
            item.origin = EvidenceOrigin.third_party_repetition
        else:
            item.group_id = by_text.get(_family_key(item.quote), _family_key(item.quote))
            while item.group_id in groups and groups[item.group_id].merged_into:
                item.group_id = groups[item.group_id].merged_into  # follow an earlier merge
        by_text.setdefault(_family_key(item.quote), item.group_id)
        group = groups.setdefault(item.group_id, EvidenceGroup(id=item.group_id, member_ids=[]))
        if not group.active:
            # A group emptied by a withdrawal is active again. Scores of its old version no longer apply.
            group.active, group.version = True, group.version + 1
            group.history.append(f"v{group.version}: {item.id} admitted again")
        group.member_ids.append(item.id)
        state.evidence.append(item)
        note(item)
        known.add((item.span_id, item.target))
    state.groups = list(groups.values())
    for item in state.evidence:
        # A repetition admitted before its original was grouped alone. Join them now, so the
        # grouping does not depend on the order of arrival.
        original = by_span.get(item.repeats_span_id or "")
        joined = {e.group_id for e in state.evidence if e.span_id == item.repeats_span_id}
        if original is not None and original.group_id and item.group_id \
                and item.group_id not in joined:
            item.origin = EvidenceOrigin.third_party_repetition
            merge(state, original.group_id, item.group_id)
    # Identical text is one observation, also when one copy was declared a repetition and the
    # other was not. The group of the declared copy is the one that is kept.
    homes: dict[str, str] = {}
    for item in sorted(state.evidence, key=lambda i: i.repeats_span_id is None):
        if item.group_id:
            home = _current(state, homes.setdefault(_family_key(item.quote), item.group_id))
            if home != item.group_id:
                merge(state, home, item.group_id)
    return evidence_hash(state.groups) != before


def _current(state: InvestigationState, group_id: str) -> str:
    """The group that holds the members of `group_id` now, after any merges."""
    groups = {g.id: g for g in state.groups}
    while groups[group_id].merged_into:
        group_id = groups[group_id].merged_into
    return group_id


def withdraw(state: InvestigationState, evidence_id: str, reason: str = "withdrawn") -> None:
    """Remove an item from the active ledger and drop what depended on it.

    The group keeps a history entry. A calculation is removed when a group it read from is no
    longer active, or when it cites the withdrawn passage and no admitted item cites it any more.
    """
    removed = [e for e in state.evidence if e.id == evidence_id]
    state.withdrawn += removed
    state.evidence = [e for e in state.evidence if e.id != evidence_id]
    uncited = {e.span_id for e in removed} - {e.span_id for e in state.evidence}
    for group in state.groups:
        if evidence_id in group.member_ids:
            group.member_ids.remove(evidence_id)
            group.version += 1
            group.active = bool(group.member_ids)
            group.history.append(f"v{group.version}: {evidence_id} {reason}")
    active = {g.id for g in state.groups if g.active}
    state.calculations = [c for c in state.calculations if set(c.lineage) <= active
                          and not uncited & {i.source_span_id for i in c.inputs}]
    for question in state.questions:
        if evidence_id in question.evidence_ids:
            question.evidence_ids.remove(evidence_id)
            if not question.evidence_ids:
                # The answer rested on the withdrawn item alone, so the question is open again.
                question.status, question.answer = AnswerStatus.open, None


def merge(state: InvestigationState, keep_id: str, drop_id: str) -> None:
    """Record that two groups are one observation. Their earlier scores no longer apply."""
    groups = {g.id: g for g in state.groups}
    if keep_id == drop_id or not (groups[keep_id].active and groups[drop_id].active):
        raise ValueError(f"cannot merge {drop_id} into {keep_id}: both must be active and distinct")
    keep, drop = groups[keep_id], groups[drop_id]
    keep.member_ids += drop.member_ids
    keep.version += 1
    keep.history.append(f"v{keep.version}: merged {drop_id}")
    drop.member_ids, drop.active, drop.merged_into = [], False, keep_id
    drop.version += 1
    drop.history.append(f"v{drop.version}: merged into {keep_id}")
    for item in state.evidence:
        if item.group_id == drop_id:
            item.group_id = keep_id
    for calculation in state.calculations:
        calculation.lineage = sorted({keep_id if g == drop_id else g for g in calculation.lineage})


def lineage(state: InvestigationState, span_ids: list[str]) -> list[str]:
    """Provenance groups of the passages a calculation reads its inputs from."""
    groups = {e.group_id for e in state.evidence if e.span_id in span_ids and e.group_id}
    return sorted(groups)
