"""Apply one investigation round to the state and record what changed."""
from __future__ import annotations

from backend.models import (
    AnswerStatus, Assessment, BeliefUpdate, EvidenceStatus, InvestigationState, Relationship,
)
from backend.providers.base import QuestionAnswer, StateUpdate


def apply_answers(state: InvestigationState, answers: list[QuestionAnswer]) -> None:
    by_span = {e.span_id: e.id for e in state.evidence}
    questions = {q.id: q for q in state.questions}
    for answer in answers:
        question = questions.get(answer.question_id)
        evidence_ids = [by_span[s] for s in answer.evidence_span_ids if s in by_span]
        # An answer that cites no admitted evidence does not mark its question as answered.
        if question is None or (answer.status == AnswerStatus.answered and not evidence_ids):
            continue
        question.status, question.answer, question.evidence_ids = \
            answer.status, answer.answer, evidence_ids


def apply_update(state: InvestigationState, update: StateUpdate, new_evidence_ids: list[str],
                 new_calculation_ids: list[str], model_version: str) -> BeliefUpdate:
    """Commit a validated assessment. The caller has already recorded evidence and calculations."""
    previous = state.assessment.status
    status, mechanisms = update.status, update.mechanisms
    # Only evidence about the claim itself counts. Support for a side question does not.
    inactive = {g.id for g in state.groups if not g.active}
    backed = {e.relationship for e in state.evidence
              if e.comparable and e.target == "claim" and e.group_id not in inactive}
    tested = {c.claim_relation for c in state.calculations}
    if (status == EvidenceStatus.supported
            and Relationship.supports not in backed and "agrees" not in tested) or (
            status == EvidenceStatus.contradicted
            and Relationship.contradicts not in backed and "disagrees" not in tested):
        # A verdict needs comparable evidence about the claim in its own direction, or a
        # calculation whose result was compared with the value the claim states. A calculation
        # that answers a side question does not justify a verdict. Without either, the claim
        # is unresolved, not false.
        status, mechanisms = EvidenceStatus.insufficient, []
    state.assessment = Assessment(status=status, mechanisms=mechanisms, summary=update.summary)
    state.unresolved = update.unresolved
    state.version += 1
    return BeliefUpdate(id=f"{state.claim.id}-u{state.version}", claim_id=state.claim.id,
                        version=state.version, previous_status=previous, new_status=status,
                        changed_evidence_ids=new_evidence_ids,
                        changed_calculation_ids=new_calculation_ids,
                        explanation=update.explanation,
                        model_version=model_version)
