"""Three ways to turn a complete candidate state into an assessment.

linguistic            the model revises the previous assessment given what changed
full_context          the model assesses from the active evidence alone, without the previous one
evidence_accumulator  the linguistic assessment plus an experimental numeric score

None of them is exact Bayesian inference. A score here is an estimate for a declared target. It
is stored for research and is never the public probability of a finding.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime
from math import isfinite

from backend.belief.accumulator import EvidenceAccumulator, EvidenceContribution
from backend.belief.state import apply_update
from backend.config import AssessmentSettings
from backend.models import (
    BeliefUpdate, Calculation, Claim, EvidenceGroup, EvidenceItem, EvidenceScore, InvestigationState,
    NumericBelief, RunManifest, ScoringTarget,
)
from backend.providers.base import LLM, ProviderError, StateUpdate

SCORER_VERSION = "llm-scorer-v2"
MAX_LOG_EVIDENCE = 5.0


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def new_target(claim: Claim, cutoff: datetime | None) -> ScoringTarget:
    return ScoringTarget(
        id=claim.rubric, claim_id=claim.id, claim_version=claim.version,
        hypothesis="H=1: the reference review, applying the rubric to this claim as worded and "
                   "to evidence admissible at the cutoff, would find a material overstatement.",
        label_space=["material_overstatement", "no_material_overstatement"], rubric=claim.rubric,
        cutoff=cutoff, protocol="No reference review data exists for this target. Scores are "
                                "uncalibrated and are not comparable across targets.")


def _target(state: InvestigationState) -> ScoringTarget:
    if state.target is None:
        raise ValueError("a score needs a declared target, and this state has none")
    return state.target


def active_evidence(state: InvestigationState) -> list[EvidenceItem]:
    active = {g.id for g in state.groups if g.active}
    return [e for e in state.evidence if e.group_id in active]


def input_hash(state: InvestigationState, strategy: str) -> str:
    """Identifies what an updater would be shown. The same hash means nothing new to decide on."""
    return _hash({
        "claim": (state.claim.id, state.claim.version, state.claim.text), "strategy": strategy,
        "evidence": [(e.id, e.quote, e.relationship, e.target, e.comparable, e.group_id)
                     for e in active_evidence(state)],
        "calculations": [(c.id, c.outputs, c.claim_relation) for c in state.calculations],
        "answers": [(q.id, q.status, q.answer) for q in state.questions]})


def context_hash(target: ScoringTarget, claim: Claim, members: list[EvidenceItem],
                 calculations: list[Calculation]) -> str:
    """A group's score is valid only for this context. A change here means it is scored again."""
    return _hash({
        "target": target.id, "cutoff": target.cutoff, "claim": (claim.text, claim.version),
        "qualifications": claim.qualifications, "scorer": SCORER_VERSION,
        "members": sorted((e.quote, e.relationship, e.comparable, tuple(e.differences))
                          for e in members),
        "calculations": sorted((c.id, str(sorted(c.outputs.items())), c.claim_relation)
                               for c in calculations)})


def units(state: InvestigationState) -> dict[str, list[EvidenceGroup]]:
    """Active groups, joined when one calculation reads from several of them.

    A calculation is derived from its input groups. Scoring each input group with the result
    would count the result once per group, so the groups are scored together and count once.
    The key joins the sorted group ids.
    """
    active = {g.id: g for g in state.groups if g.active}
    root = {g: g for g in active}

    def find(group_id: str) -> str:
        while root[group_id] != group_id:
            group_id = root[group_id]
        return group_id

    for calculation in state.calculations:
        linked = [g for g in calculation.lineage if g in active]
        for other in linked[1:]:
            root[find(other)] = find(linked[0])
    joined: dict[str, list[EvidenceGroup]] = {}
    for group_id in sorted(active):
        joined.setdefault(find(group_id), []).append(active[group_id])
    return {"+".join(g.id for g in members): members for members in joined.values()}


def _version(members: list[EvidenceGroup]) -> int:
    # Group versions only increase, so the sum changes whenever any member group changes.
    return sum(g.version for g in members)


def accumulate(state: InvestigationState, settings: AssessmentSettings) -> NumericBelief:
    """Recompute the score from the scores of the current units. Nothing is carried over."""
    current = {key: _version(members) for key, members in units(state).items()}
    ledger = EvidenceAccumulator(settings.prior, settings.tempering)
    used = [s for s in state.scores if current.get(s.group_id) == s.group_version]
    for score in used:
        ledger.upsert(EvidenceContribution(score.group_id, score.group_version, score.log_evidence))
    return NumericBelief(
        target_id=_target(state).id, method="evidence_accumulator", prior=settings.prior,
        prior_provenance="neutral scenario prior, not estimated from data",
        raw_logit=ledger.raw_logit(), raw_probability=ledger.raw_probability(), contributions=used)


def score_groups(state: InvestigationState, llm: LLM, manifest: RunManifest) -> None:
    """Score each unit once per conditioning context. A failed score adds nothing."""
    kept: list[EvidenceScore] = []
    for key, groups in units(state).items():
        ids = {g.id for g in groups}
        members = [e for e in state.evidence if e.group_id in ids]
        related = [c for c in state.calculations if ids & set(c.lineage)]
        context = context_hash(_target(state), state.claim, members, related)
        cached = next((s for s in state.scores if s.group_id == key
                       and s.group_version == _version(groups)
                       and s.conditioning_context_hash == context), None)
        if cached is not None:
            kept.append(cached)
            continue
        try:
            draft = llm.score_evidence(_target(state), state.claim, members, related)
        except ProviderError as exc:
            manifest.errors.append(f"evidence score unavailable for {key}: {exc}")
            continue
        if not isfinite(draft.log_evidence) or abs(draft.log_evidence) > MAX_LOG_EVIDENCE:
            # An unusable score is an abstention. It is not treated as zero or as evidence.
            manifest.rejections.append(
                f"evidence score rejected for {key}: not finite or outside the limit")
            continue
        member_ids = {e.id for e in members}
        kept.append(EvidenceScore(
            group_id=key, group_version=_version(groups), log_evidence=draft.log_evidence,
            method="llm_estimated", short_basis=draft.short_basis,
            supporting_evidence_ids=[i for i in draft.supporting_evidence_ids if i in member_ids],
            conditioning_context_hash=context, scorer_version=SCORER_VERSION))
    state.scores = kept


def _agreed(state: InvestigationState, new_evidence_ids: list[str], new_calculation_ids: list[str],
            llm: LLM, samples: int) -> StateUpdate:
    """Ask the updater `samples` times and keep the status the samples agree on most often.

    One sample decides a verdict on its own, and the same state can produce different statuses on
    identical runs. The answer returned is a whole sample, so its summary and explanation match
    the status it came with. A tie is settled by the first sample that reached the winning status.
    """
    drafts = [llm.update_state(state, new_evidence_ids, new_calculation_ids)
              for _ in range(max(1, samples))]
    if len(drafts) == 1:
        return drafts[0]
    counts = Counter(d.status for d in drafts)
    best = max(counts, key=lambda status: (counts[status], -[d.status for d in drafts].index(status)))
    return next(d for d in drafts if d.status == best)


def run(state: InvestigationState, new_evidence_ids: list[str], new_calculation_ids: list[str],
        llm: LLM, settings: AssessmentSettings,
        manifest: RunManifest) -> tuple[StateUpdate, NumericBelief | None]:
    """Apply the configured strategy to a state that already holds the round's observations."""
    if settings.updater == "full_context":
        # One representative per provenance group, and no earlier verdict or score.
        # The member shown for a group is one about the claim on the same basis, if there is one,
        # and an original before a repetition.
        shown: dict[str | None, EvidenceItem] = {}
        for e in sorted(active_evidence(state), key=lambda e: (
                e.target != "claim", not e.comparable, e.repeats_span_id is not None)):
            shown.setdefault(e.group_id, e)
        evidence = [e for e in active_evidence(state) if shown[e.group_id] is e]
        result = llm.reassess(_target(state), state.claim, evidence, state.calculations,
                              state.questions)
        p = result.probability
        belief = NumericBelief(target_id=_target(state).id, method="full_context",
                               raw_probability=p if p is not None and 0.0 < p < 1.0 else None)
        return StateUpdate(**result.model_dump(exclude={"probability"})), belief
    if settings.updater not in ("linguistic", "evidence_accumulator"):
        raise ValueError(f"unknown updater: {settings.updater}")
    update = _agreed(state, new_evidence_ids, new_calculation_ids, llm, settings.updater_samples)
    if settings.updater == "linguistic":
        return update, None
    score_groups(state, llm, manifest)
    return update, accumulate(state, settings)


def step(state: InvestigationState, new_evidence_ids: list[str], new_calculation_ids: list[str],
         llm: LLM, settings: AssessmentSettings, manifest: RunManifest,
         model_version: str) -> BeliefUpdate | None:
    """Run the strategy once and commit the result. The worker and the replay both call this.

    Return None when the input is the same as the input of the last committed update, so a
    retry cannot record a second update or change a score. A ProviderError leaves the state as
    it was.
    """
    shown = input_hash(state, settings.updater)
    if shown == state.last_input_hash:
        return None
    previous = state.belief.raw_probability if state.belief else None
    update, belief = run(state, new_evidence_ids, new_calculation_ids, llm, settings, manifest)
    record = apply_update(state, update, new_evidence_ids, new_calculation_ids, model_version)
    state.belief, state.last_input_hash = belief, shown
    record.strategy, record.input_state_hash = settings.updater, shown
    record.belief, record.previous_score = belief, previous
    record.new_score = belief.raw_probability if belief else None
    return record
