"""Check a proposed conclusion against the original passages, then build the finding."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from backend.belief.priority import critical_open
from backend.models import (
    Assessment, EvidenceStatus, Finding, InvestigationState, ReviewState, RunManifest, SourceSpan, Uncertainty,
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


def numbers_supported(text: str, state: InvestigationState, spans: dict[str, SourceSpan]) -> bool:
    """Model-written text may use only numbers found in the claim, the evidence, or the calculations."""
    allowed = _numbers(state.claim.text)
    for item in state.evidence:
        allowed |= _numbers(spans[item.span_id].text) if item.span_id in spans else set()
    outputs = [abs(v) for c in state.calculations for v in c.outputs.values()]
    # A rewrite may state a calculated result rounded to the precision it is written with.
    return all(n in allowed or any(abs(v - n) * 2 <= Decimal(1).scaleb(int(n.as_tuple().exponent))
                                   for v in outputs) for n in _numbers(text))


def run_review(state: InvestigationState, spans: dict[str, SourceSpan], llm: LLM,
               manifest: RunManifest | None = None) -> ReviewResult | None:
    """Ask for a review when there is something to review. None means no review was made."""
    if citation_errors(state, spans) or not (state.evidence or state.calculations):
        return None
    decisive = [spans[e.span_id] for e in state.evidence if e.span_id in spans]
    try:
        return llm.review(state, decisive)
    except ProviderError as exc:
        if manifest is not None:
            manifest.errors.append(str(exc))
        return None


def finalize(state: InvestigationState, spans: dict[str, SourceSpan], llm: LLM,
             review: ReviewResult | None, cutoff: datetime | None = None,
             manifest: RunManifest | None = None) -> Finding:
    claim = state.claim

    def checked(text: str) -> str:
        # The fixed sentence names the status at the time it is used, after any review.
        fallback = f"Assessment: {state.assessment.status}. See the evidence and calculations."
        return text if text and numbers_supported(text, state, spans) else fallback

    finding = Finding(finding_id=f"{claim.id}-f{state.version}", claim_id=claim.id,
                      claim_version=claim.version, target_rubric=claim.rubric,
                      evidence_status=state.assessment.status,
                      mechanisms=state.assessment.mechanisms,
                      summary=checked(state.assessment.summary),
                      evidence_ids=[e.id for e in state.evidence],
                      calculation_ids=[c.id for c in state.calculations],
                      evidence_cutoff=cutoff, stop_reason=state.stop_reason)
    finding.uncertainty = Uncertainty(critical_missing_questions=critical_open(state.questions))
    errors = citation_errors(state, spans)
    if errors:
        finding.review_status = ReviewState.blocked
        finding.uncertainty.measurement_limitations = errors
        return finding
    if not state.evidence and not state.calculations:
        # Nothing was admitted, so there is nothing to review and no wording to propose.
        finding.summary = "No evidence for this claim was found in the allowed sources."
        return finding
    decisive = [spans[e.span_id] for e in state.evidence if e.span_id in spans]
    if review is None:
        finding.uncertainty.measurement_limitations = ["review did not run"]
        return finding
    # Review reasons are model text, so they follow the same number rule as the summary.
    reasons = [r for r in review.reasons if numbers_supported(r, state, spans)]
    weaker = (EvidenceStatus.mixed, EvidenceStatus.insufficient, EvidenceStatus.not_yet_resolvable)
    decided = state.assessment.status in (EvidenceStatus.supported, EvidenceStatus.contradicted)
    if review.decision == "reject":
        state.assessment = Assessment(status=EvidenceStatus.insufficient,
                                      summary="Review rejected the proposed conclusion.")
    elif review.decision == "narrow" and review.narrowed_status in weaker and decided:
        # A review can weaken a verdict. It cannot introduce supported or contradicted. The
        # summary and mechanisms of the earlier verdict no longer describe the assessment.
        mechanisms = state.assessment.mechanisms if review.narrowed_status == EvidenceStatus.mixed else []
        state.assessment = Assessment(status=review.narrowed_status, mechanisms=mechanisms)
        finding.summary = checked("")
    finding.evidence_status = state.assessment.status
    finding.mechanisms = state.assessment.mechanisms
    if review.decision == "reject":
        finding.summary = state.assessment.summary
        finding.uncertainty.measurement_limitations = reasons
        return finding
    if review.decision == "request_check":
        # A check that is still an open question is already listed above.
        listed = finding.uncertainty.critical_missing_questions
        listed += [f"Review requested a check that was not completed: {r}" for r in reasons
                   if r not in listed]
    try:
        # The report is written from the reviewed assessment, not the one the review started from.
        report: Report = llm.report(state, decisive)
    except ProviderError as exc:
        if manifest is not None:
            manifest.errors.append(str(exc))
        finding.uncertainty.measurement_limitations = [f"report did not run: {exc}"] + (
            reasons if review.decision != "accept" else [])
        return finding
    finding.summary = checked(report.summary)
    if report.supported_rewrite and numbers_supported(report.supported_rewrite, state, spans):
        finding.supported_rewrite = report.supported_rewrite
    finding.uncertainty.source_independence = report.source_independence
    finding.uncertainty.measurement_limitations = report.measurement_limitations + (
        reasons if review.decision != "accept" else [])
    finding.uncertainty.interpretation_ambiguity = report.interpretation_ambiguity
    if review.decision == "accept":
        finding.review_status = ReviewState.checks_passed
    return finding
