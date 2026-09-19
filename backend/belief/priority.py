"""Heuristic ordering of open questions, and checklist coverage. Neither is a probability."""
from __future__ import annotations

from backend.models import AnswerStatus, VerificationQuestion

EPSILON = 0.5


def priority(question: VerificationQuestion) -> float:
    unresolved = 1.0 if question.status == AnswerStatus.open else 0.0
    return question.materiality * unresolved * question.answerability / (question.cost + EPSILON)


def choose(questions: list[VerificationQuestion], limit: int = 3) -> list[VerificationQuestion]:
    ranked = sorted((q for q in questions if priority(q) > 0), key=priority, reverse=True)
    return ranked[:limit]


def coverage(questions: list[VerificationQuestion]) -> float:
    total = sum(q.materiality for q in questions)
    answered = sum(q.materiality for q in questions if q.status == AnswerStatus.answered)
    return answered / total if total else 0.0


def critical_open(questions: list[VerificationQuestion]) -> list[str]:
    return [q.text for q in questions if q.critical and q.status != AnswerStatus.answered]
