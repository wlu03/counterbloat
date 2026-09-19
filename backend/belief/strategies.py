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
from datetime import datetime
from math import isfinite

from backend.belief.accumulator import EvidenceAccumulator, EvidenceContribution
from backend.belief.state import apply_update
from backend.config import AssessmentSettings
from backend.models import (
    BeliefUpdate, Calculation, Claim, EvidenceItem, EvidenceScore, InvestigationState,
    NumericBelief, RunManifest, ScoringTarget,
)
from backend.providers.base import LLM, ProviderError, StateUpdate

SCORER_VERSION = "llm-scorer-v1"
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


def accumulate(state: InvestigationState, settings: AssessmentSettings) -> NumericBelief:
    """Recompute the score from the scores of the active groups. Nothing is carried over."""
    active = {g.id: g for g in state.groups if g.active}
    ledger = EvidenceAccumulator(settings.prior, settings.tempering)
    used = [s for s in state.scores if s.group_id in active
            and s.group_version == active[s.group_id].version]
    for score in used:
        ledger.upsert(EvidenceContribution(score.group_id, score.group_version, score.log_evidence))
    return NumericBelief(
        target_id=state.target.id, method="evidence_accumulator", prior=settings.prior,
        prior_provenance="neutral scenario prior, not estimated from data",
        raw_logit=ledger.raw_logit(), raw_probability=ledger.raw_probability(), contributions=used)


def score_groups(state: InvestigationState, llm: LLM, manifest: RunManifest) -> None:
    """Score each active group once per conditioning context. A failed score adds nothing."""
    kept: list[EvidenceScore] = []
    for group in (g for g in state.groups if g.active):
        members = [e for e in state.evidence if e.group_id == group.id]
        related = [c for c in state.calculations if group.id in c.lineage]
        context = context_hash(state.target, state.claim, members, related)
        cached = next((s for s in state.scores if s.group_id == group.id
                       and s.group_version == group.version
                       and s.conditioning_context_hash == context), None)
        if cached is not None:
            kept.append(cached)
            continue
        try:
            draft = llm.score_evidence(state.target, state.claim, members, related)
        except ProviderError as exc:
            manifest.errors.append(f"evidence score unavailable for {group.id}: {exc}")
            continue
        if not isfinite(draft.log_evidence) or abs(draft.log_evidence) > MAX_LOG_EVIDENCE:
            # An unusable score is an abstention. It is not treated as zero or as evidence.
            manifest.rejections.append(
                f"evidence score rejected for {group.id}: {draft.log_evidence}")
            continue
        member_ids = {e.id for e in members}
        kept.append(EvidenceScore(
            group_id=group.id, group_version=group.version, log_evidence=draft.log_evidence,
            method="llm_estimated", short_basis=draft.short_basis,
            supporting_evidence_ids=[i for i in draft.supporting_evidence_ids if i in member_ids],
            conditioning_context_hash=context, scorer_version=SCORER_VERSION))
    state.scores = kept


def run(state: InvestigationState, new_evidence_ids: list[str], new_calculation_ids: list[str],
        llm: LLM, settings: AssessmentSettings,
        manifest: RunManifest) -> tuple[StateUpdate, NumericBelief | None]:
    """Apply the configured strategy to a state that already holds the round's observations."""
    if settings.updater == "full_context":
        # One representative per provenance group, and no earlier verdict or score.
        seen: set[str] = set()
        evidence = [e for e in active_evidence(state)
                    if not (e.group_id in seen or seen.add(e.group_id))]
        result = llm.reassess(state.target, state.claim, evidence, state.calculations,
                              state.questions)
        p = result.probability
        belief = NumericBelief(target_id=state.target.id, method="full_context",
                               raw_probability=p if p is not None and 0.0 < p < 1.0 else None)
        return StateUpdate(**result.model_dump(exclude={"probability"})), belief
    update = llm.update_state(state, new_evidence_ids, new_calculation_ids)
    if settings.updater == "linguistic":
        return update, None
    score_groups(state, llm, manifest)
    return update, accumulate(state, settings)


def step(state: InvestigationState, new_evidence_ids: list[str], new_calculation_ids: list[str],
         llm: LLM, settings: AssessmentSettings, manifest: RunManifest,
         model_version: str) -> BeliefUpdate | None:
    """Run the strategy once and commit the result. The worker and the replay both call this.

    Return None when the state holds nothing the last committed update did not already see, so a
    retry cannot record a second update or move a score. A ProviderError leaves the state as it was.
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
