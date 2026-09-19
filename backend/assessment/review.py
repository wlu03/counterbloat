"""Check a proposed conclusion against the original passages, then build the finding."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from backend.belief.priority import critical_open
from backend.models import (
    EvidenceStatus, Finding, InvestigationState, ReviewState, SourceSpan, Uncertainty,
)
from backend.providers.base import LLM, ProviderError, Report, ReviewResult
from backend.verification.numeric import CalculationError, execute, value_in_source


def citation_errors(state: InvestigationState, spans: dict[str, SourceSpan]) -> list[str]:
    """Every quote must exist in its passage, and every calculation must reproduce."""
    errors = []
    for item in state.evidence:
        span = spans.get(item.span_id)
        if span is None or item.quote not in span.text:
            errors.append(f"quote for {item.id} is not in its source passage")
    for calc in state.calculations:
        for value in calc.inputs:
            span = spans.get(value.source_span_id)
            if span is None or not value_in_source(value.value, span):
                errors.append(f"input {value.name} of {calc.id} is not in its source passage")
        try:
            if execute(calc.id, calc.claim_id, calc.inputs, calc.steps).outputs != calc.outputs:
                errors.append(f"{calc.id} does not reproduce")
        except CalculationError as exc:
            errors.append(f"{calc.id} failed: {exc}")
    return errors


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", text)}


def rewrite_is_supported(rewrite: str, state: InvestigationState,
                         spans: dict[str, SourceSpan]) -> bool:
    """A rewrite may use only numbers found in the claim, the evidence, or the calculations."""
    allowed = _numbers(state.claim.text)
    for item in state.evidence:
        allowed |= _numbers(spans[item.span_id].text) if item.span_id in spans else set()
    for calc in state.calculations:
        allowed |= {abs(v).normalize() for v in calc.outputs.values()}
    return all(any(n == a for a in allowed) for n in _numbers(rewrite))


def finalize(state: InvestigationState, spans: dict[str, SourceSpan], llm: LLM,
             cutoff: datetime | None = None) -> Finding:
    claim = state.claim
    finding = Finding(finding_id=f"{claim.id}-f{state.version}", claim_id=claim.id,
                      claim_version=claim.version, target_rubric=claim.rubric,
                      evidence_status=state.assessment.status,
                      mechanisms=state.assessment.mechanisms, summary=state.assessment.summary,
                      evidence_ids=[e.id for e in state.evidence],
                      calculation_ids=[c.id for c in state.calculations],
                      evidence_cutoff=cutoff, stop_reason=state.stop_reason)
    finding.uncertainty = Uncertainty(critical_missing_questions=critical_open(state.questions))
    errors = citation_errors(state, spans)
    if errors:
        finding.review_status = ReviewState.blocked
        finding.uncertainty.measurement_limitations = errors
        return finding
    decisive = [spans[e.span_id] for e in state.evidence if e.span_id in spans]
    try:
        review: ReviewResult = llm.review(state, decisive)
        report: Report = llm.report(state, decisive)
    except ProviderError as exc:
        finding.uncertainty.measurement_limitations = [f"review did not run: {exc}"]
        return finding
    if review.decision == "reject":
        finding.evidence_status, finding.mechanisms = EvidenceStatus.insufficient, []
        finding.summary = "Review rejected the proposed conclusion: " + "; ".join(review.reasons)
        return finding
    if review.decision == "narrow" and review.narrowed_status:
        finding.evidence_status = review.narrowed_status
    finding.summary = report.summary
    if report.supported_rewrite and rewrite_is_supported(report.supported_rewrite, state, spans):
        finding.supported_rewrite = report.supported_rewrite
    finding.uncertainty.source_independence = report.source_independence
    finding.uncertainty.measurement_limitations = report.measurement_limitations + (
        review.reasons if review.decision != "accept" else [])
    finding.uncertainty.interpretation_ambiguity = report.interpretation_ambiguity
    if review.decision == "accept":
        finding.review_status = ReviewState.checks_passed
    return finding
