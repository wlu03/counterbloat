"""Apply one investigation round to the state and record what changed."""
from __future__ import annotations

from backend.models import (
    AnswerStatus, Assessment, BeliefUpdate, Calculation, EvidenceStatus, InvestigationState,
)
from backend.providers.base import QuestionAnswer, StateUpdate


def apply_answers(state: InvestigationState, answers: list[QuestionAnswer]) -> None:
    by_span = {e.span_id: e.id for e in state.evidence}
    questions = {q.id: q for q in state.questions}
    for answer in answers:
        question = questions.get(answer.question_id)
        evidence_ids = [by_span[s] for s in answer.evidence_span_ids if s in by_span]
        # An answer with no admitted evidence behind it does not close a question.
        if question is None or (answer.status == AnswerStatus.answered and not evidence_ids):
            continue
        question.status, question.answer, question.evidence_ids = \
            answer.status, answer.answer, evidence_ids


def apply_update(state: InvestigationState, update: StateUpdate, new_evidence_ids: list[str],
                 calculations: list[Calculation], model_version: str) -> BeliefUpdate:
    previous = state.assessment.status
    state.calculations += calculations
    status, mechanisms = update.status, update.mechanisms
    if not any(g.active for g in state.groups) and not state.calculations:
        # A verdict needs admitted evidence. Without any, the claim is unresolved, not false.
        status, mechanisms = EvidenceStatus.insufficient, []
    state.assessment = Assessment(status=status, mechanisms=mechanisms, summary=update.summary)
    state.unresolved = update.unresolved
    state.version += 1
    return BeliefUpdate(id=f"{state.claim.id}-u{state.version}", claim_id=state.claim.id,
                        version=state.version, previous_status=previous, new_status=status,
                        changed_evidence_ids=new_evidence_ids, explanation=update.explanation,
                        model_version=model_version)
