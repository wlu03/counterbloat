"""A rule-based provider for replays that must not make paid calls.

It checks ordering, duplicate, and withdrawal behaviour. It does not estimate anything: the
status follows a fixed rule and the scores are the ones recorded in the trace.
"""
from __future__ import annotations

from backend.models import EvidenceStatus, Relationship
from backend.providers.base import EvidenceScoreDraft, ProviderError, Reassessment, StateUpdate


def _status(evidence, calculations) -> EvidenceStatus:
    relations = {e.relationship for e in evidence if e.comparable and e.target == "claim"}
    tested = {c.claim_relation for c in calculations}
    against = Relationship.contradicts in relations or "disagrees" in tested
    in_favour = Relationship.supports in relations or "agrees" in tested
    if against and in_favour:
        return EvidenceStatus.mixed
    if against:
        return EvidenceStatus.contradicted
    return EvidenceStatus.supported if in_favour else EvidenceStatus.insufficient


def context_key(evidence, calculations) -> str:
    """Names what a recorded score was given: the source groups, how their passages relate to the
    claim, and the calculations."""
    return "#".join("+".join(sorted(set(part))) for part in (
        [e.group_id for e in evidence], [e.relationship for e in evidence],
        [c.id for c in calculations]))


class ScriptedLLM:
    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores

    def update_state(self, state, new_evidence_ids, new_calculation_ids) -> StateUpdate:
        return StateUpdate(status=_status(state.evidence, state.calculations), mechanisms=[],
                           summary="", unresolved=[], explanation="fixed rule, no model call")

    def reassess(self, target, claim, evidence, calculations, questions) -> Reassessment:
        # The rule has no probability estimate, so none is reported.
        return Reassessment(status=_status(evidence, calculations), mechanisms=[], summary="",
                            unresolved=[], explanation="fixed rule, no model call",
                            probability=None)

    def score_evidence(self, target, claim, evidence, calculations) -> EvidenceScoreDraft:
        # A recorded score applies to the groups and calculations it was made for and to nothing
        # else. For any other context the provider abstains.
        key = context_key(evidence, calculations)
        if key not in self.scores:
            raise ProviderError("no recorded score for this context")
        return EvidenceScoreDraft(log_evidence=self.scores[key], short_basis="recorded in the trace",
                                  supporting_evidence_ids=[e.id for e in evidence])
