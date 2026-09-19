"""Regression tests for defects found in code review."""
from decimal import Decimal

import pytest

from backend.assessment.review import finalize, numbers_supported, run_review
from backend.belief.state import apply_update
from backend.claims.extract import valid
from backend.config import Settings
from backend.evidence.provenance import reconcile
from backend.models import (
    AssertionType, CalcInput, CalcStep, Claim, EvidenceItem, EvidenceStatus, InvestigationState,
    Relationship, SourceSpan,
)
from backend.providers.base import ClaimDraft, Report, ReviewResult, StateUpdate
from backend.verification.numeric import CalculationError, execute


def _claim():
    return Claim(id="c", document_id="d", span_id="s0", text="Emissions fell 40%.", start=0, end=19,
                 assertion_type=AssertionType.reported_achievement)


def _item(i, span, quote, relationship=Relationship.supports, comparable=True):
    return EvidenceItem(id=f"e{i}", claim_id="c", span_id=span, document_id="d", quote=quote,
                        relationship=relationship, target="claim", comparable=comparable)


def _update(status):
    return StateUpdate(status=status, mechanisms=[], summary="s", unresolved=[], explanation="e")


def test_a_verdict_needs_comparable_evidence_in_its_own_direction():
    state = InvestigationState(claim=_claim())
    reconcile(state, [_item(1, "s1", "Per-unit emissions fell 40%.", comparable=False)], {})
    apply_update(state, _update(EvidenceStatus.supported), ["e1"], [], "v")
    assert state.assessment.status == EvidenceStatus.insufficient
    reconcile(state, [_item(2, "s2", "Total emissions fell 40%.")], {})
    apply_update(state, _update(EvidenceStatus.supported), ["e2"], [], "v")
    assert state.assessment.status == EvidenceStatus.supported


class _Narrowing:
    def review(self, state, decisive):
        return ReviewResult(decision="narrow", narrowed_status="contradicted", reasons=["r"])

    def report(self, state, decisive):
        return Report(summary="s", supported_rewrite=None, source_independence="",
                      measurement_limitations=[], interpretation_ambiguity="")


def _state_with_context():
    state = InvestigationState(claim=_claim())
    reconcile(state, [_item(1, "s1", "Output doubled.", Relationship.context)], {})
    spans = {"s1": SourceSpan(id="s1", document_id="d", kind="paragraph", text="Output doubled.",
                              start=0, end=15)}
    return state, spans


def test_review_cannot_strengthen_a_verdict():
    state, spans = _state_with_context()
    finding = finalize(state, spans, _Narrowing(), run_review(state, spans, _Narrowing()))
    assert finding.evidence_status == EvidenceStatus.insufficient


def test_a_claim_with_no_evidence_skips_the_review_calls():
    class Unreachable:
        def review(self, state, decisive):
            raise AssertionError("review must not be called")

    empty = InvestigationState(claim=_claim())
    finding = finalize(empty, {}, Unreachable(), run_review(empty, {}, Unreachable()))
    assert finding.evidence_status == EvidenceStatus.insufficient
    assert finding.summary.startswith("No evidence")


def test_repeat_is_grouped_with_its_original_in_either_order():
    state = InvestigationState(claim=_claim())
    repeat, original = _item(1, "s3", "Intensity dropped two fifths"), _item(2, "s1", "Fell 40%.")
    reconcile(state, [repeat, original], {"s3": "s1"})
    assert len(state.groups) == 1


def test_multiply_rejects_mixed_periods_and_unrelated_rates():
    def value(name, number, unit, period):
        return CalcInput(name=name, value=Decimal(number), unit=unit, period=period,
                         source_span_id="s")
    step = [CalcStep(op="multiply", args=["a", "b"], out="x")]
    with pytest.raises(CalculationError):
        execute("c", "claim", [value("a", "10", "kg CO2e/unit", "2024"),
                               value("b", "2000", "unit", "2025")], step)
    with pytest.raises(CalculationError):
        execute("c", "claim", [value("a", "10", "kg CO2e/unit", "2024"),
                               value("b", "500", "employees", "2024")], step)
    worded = execute("c", "claim", [value("a", "10", "kg CO2e/unit", "2024"),
                                    value("b", "1000", "units produced", "2024")], step)
    assert worded.outputs["x"] == Decimal(10000) and worded.units["x"] == "kg CO2e"


def test_claim_value_must_be_a_number_in_the_quote():
    span = SourceSpan(id="s", document_id="d", kind="paragraph", start=0, end=1,
                      text="We reduced emissions by 40% in 2025 compared with 2024.")

    def draft(value):
        return ClaimDraft(quote=span.text, assertion_type="reported_achievement", subject=None,
                          assertion=None, metric=None, value=value, unit=None, denominator=None,
                          population=None, boundary=None, period=None, qualifications=[])
    assert valid(draft("40"), span) and not valid(draft("25"), span)


def test_rewrite_may_round_a_calculated_result():
    state = InvestigationState(claim=_claim())
    inputs = [CalcInput(name="a", value=Decimal(120), unit="t", source_span_id="s"),
              CalcInput(name="b", value=Decimal(70), unit="t", source_span_id="s")]
    state.calculations = [execute("n", "c", inputs, [CalcStep(op="reduction", args=["a", "b"], out="r")])]
    assert numbers_supported("Emissions fell 41.7%.", state, {})
    assert numbers_supported("Emissions fell about 42%.", state, {})
    assert not numbers_supported("Emissions fell 45%.", state, {})


def test_bad_settings_fail_when_loaded():
    with pytest.raises(ValueError):
        Settings.model_validate({"assessment": {"updater": "tempered"}})


class _Inventing(_Narrowing):
    def review(self, state, decisive):
        return ReviewResult(decision="accept", narrowed_status=None, reasons=[])

    def report(self, state, decisive):
        return Report(summary="Totals rose from 10,000 to 12,000 kg.", supported_rewrite=None,
                      source_independence="", measurement_limitations=[],
                      interpretation_ambiguity="")


def test_summary_with_numbers_no_calculation_produced_is_replaced():
    state, spans = _state_with_context()
    finding = finalize(state, spans, _Inventing(), run_review(state, spans, _Inventing()))
    assert "10,000" not in finding.summary and finding.summary.startswith("Assessment:")
