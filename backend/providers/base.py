"""Interfaces the application calls, and the structured shapes providers must return."""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel

from backend.models import (
    AnswerStatus, AssertionType, CalcStep, Claim, EvidenceOrigin, EvidenceStatus,
    InvestigationState, Mechanism, Relationship, SourceSpan, VerificationQuestion,
)


class ProviderError(Exception):
    """A provider call failed. This is an operational error, never evidence about a claim."""


class ClaimDraft(BaseModel):
    quote: str
    assertion_type: AssertionType
    subject: str | None
    assertion: str | None
    metric: str | None
    value: str | None
    unit: str | None
    denominator: str | None
    population: str | None
    boundary: str | None
    period: str | None
    qualifications: list[str]


class ClaimDrafts(BaseModel):
    claims: list[ClaimDraft]


class QuestionDraft(BaseModel):
    text: str
    why_it_matters: str
    evidence_needed: str
    materiality: int
    answerability: int
    critical: bool


class QuestionDrafts(BaseModel):
    questions: list[QuestionDraft]


class EvidenceJudgment(BaseModel):
    span_id: str
    quote: str
    relationship: Relationship
    target: str  # "claim" or a question id
    # Fields on which the passage measures something different from the claim.
    differs_on: list[Literal["metric", "unit", "denominator", "population", "boundary", "period"]]
    origin: EvidenceOrigin
    repeats_span_id: str | None
    limitations: list[str]


class InputDraft(BaseModel):
    name: str  # short name that steps refer to, such as i24
    value: str  # the number as written in the passage
    unit: str
    period: str | None
    population: str | None
    boundary: str | None
    source_span_id: str


class ProgramDraft(BaseModel):
    inputs: list[InputDraft]
    steps: list[CalcStep]
    note: str
    # Set only when the calculation tests the claim itself: the step whose result measures the
    # quantity the claim states, and the claim's stated value on that result's convention.
    claim_output: str | None
    claim_expected: str | None


class QuestionAnswer(BaseModel):
    question_id: str
    status: AnswerStatus
    answer: str | None
    evidence_span_ids: list[str]


class EvidenceAnalysis(BaseModel):
    judgments: list[EvidenceJudgment]
    programs: list[ProgramDraft]
    answers: list[QuestionAnswer]


class StateUpdate(BaseModel):
    status: EvidenceStatus
    mechanisms: list[Mechanism]
    summary: str
    unresolved: list[str]
    explanation: str


class ReviewResult(BaseModel):
    decision: Literal["accept", "narrow", "reject", "request_check"]
    narrowed_status: EvidenceStatus | None
    reasons: list[str]


class Report(BaseModel):
    summary: str
    supported_rewrite: str | None
    source_independence: str
    measurement_limitations: list[str]
    interpretation_ambiguity: str


class Route(BaseModel):
    is_claim: bool
    confidence: float = 0.0


class Compressed(BaseModel):
    output: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    def extract_claims(self, span: SourceSpan, context: list[SourceSpan]) -> list[ClaimDraft]: ...
    def plan_questions(self, claim: Claim, checklist: list[str]) -> list[QuestionDraft]: ...
    def analyze_evidence(self, claim: Claim, questions: list[VerificationQuestion],
                         context: str) -> EvidenceAnalysis: ...
    def update_state(self, state: InvestigationState, new_evidence_ids: list[str],
                     new_calculation_ids: list[str]) -> StateUpdate: ...
    def review(self, state: InvestigationState, decisive: list[SourceSpan]) -> ReviewResult: ...
    def report(self, state: InvestigationState, decisive: list[SourceSpan]) -> Report: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...
    def discover(self, query: str) -> list[str]: ...


class Router(Protocol):
    def route(self, text: str) -> Route: ...


class Compressor(Protocol):
    def compress(self, text: str) -> Compressed: ...
