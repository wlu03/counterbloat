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
    Mechanism, Relationship, SourceSpan,
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


def test_a_supplied_claim_is_read_rather_than_searched_for(store):
    from backend.claims.extract import structure
    from backend.models import Mode, RunManifest, SourceSpan
    from backend.providers.base import ClaimDraft, ProviderError
    from tests.fakes import FakeLLM

    span = SourceSpan(id="s1", document_id="d", kind="paragraph", start=10, end=60,
                      text="Everybody knows that the Pacific island of Tuvalu is sinking.")
    manifest = RunManifest(analysis_id="a", mode=Mode.frozen, config_hash="")

    class Refusing(FakeLLM):
        def extract_claims(self, span, context):
            return []  # the extractor declines a general statement of fact

        def structure_claim(self, text, span):
            return ClaimDraft(quote=text, assertion_type="capability", subject="Tuvalu",
                              assertion="is sinking", metric=None, value=None, unit=None,
                              denominator=None, population=None, boundary=None, period=None,
                              qualifications=[])

    [claim] = structure("the Pacific island of Tuvalu is sinking", [span], Refusing(), manifest)
    assert claim.text == "the Pacific island of Tuvalu is sinking" and claim.span_id == "s1"
    assert claim.start == 10 + span.text.index(claim.text) and claim.id.endswith("s1-c0")

    # A claim that is not in any passage cannot be pointed at, and a number the wording does not
    # state cannot come from it.
    assert structure("a sentence from somewhere else", [span], Refusing(), manifest) == []
    assert "not a verbatim quote" in manifest.rejections[0]

    class Inventing(FakeLLM):
        def structure_claim(self, text, span):
            return ClaimDraft(quote=text, assertion_type="capability", subject=None, assertion=None,
                              metric=None, value="40", unit="%", denominator=None, population=None,
                              boundary=None, period=None, qualifications=[])

    assert structure("the Pacific island of Tuvalu is sinking", [span], Inventing(), manifest) == []
    assert "state a number" in manifest.rejections[1]

    class Broken(FakeLLM):
        def structure_claim(self, text, span):
            raise ProviderError("openai structure failed: 503")

    assert structure("the Pacific island of Tuvalu is sinking", [span], Broken(), manifest) == []
    assert "503" in manifest.errors[0]


def test_a_supplied_claim_is_normalised_the_way_its_document_was(store):
    """The parser rewrites an ellipsis character, so the raw claim is no longer a substring of
    the passage it came from. It should still be found."""
    from backend.claims.extract import structure
    from backend.ingestion.snapshot import admit
    from backend.models import Mode, RunManifest
    from tests.fakes import FakeLLM

    class Reader(FakeLLM):
        def structure_claim(self, text, span):
            return ClaimDraft(quote=text, assertion_type="capability", subject="water vapour",
                              assertion="is the main greenhouse gas", metric=None, value=None,
                              unit=None, denominator=None, population=None, boundary=None,
                              period=None, qualifications=[])

    raw = "The main greenhouse gas is water vapour[…]"
    _, spans = admit(store, f"<html><body><p>{raw}</p></body></html>".encode(), "text/html")
    manifest = RunManifest(analysis_id="a", mode=Mode.frozen, config_hash="")
    [claim] = structure(raw, spans, Reader(), manifest)
    assert claim.text == "The main greenhouse gas is water vapour[...]"
    assert claim.text in spans[0].text and manifest.rejections == []


def test_a_summary_written_for_a_verdict_the_gate_rejects_is_not_kept():
    from backend.belief.state import GATED_SUMMARY

    state = InvestigationState(claim=_claim())
    proves = StateUpdate(status=EvidenceStatus.contradicted, mechanisms=[],
                         summary="The evidence proves this claim false.", unresolved=[],
                         explanation="e")
    record = apply_update(state, proves, [], [], "v")
    # No comparable evidence contradicts the claim, so the gate writes insufficient. Keeping the
    # model's sentence would leave the report asserting a verdict the record does not hold.
    assert record.new_status == EvidenceStatus.insufficient
    assert record.proposed_status == EvidenceStatus.contradicted
    assert state.assessment.summary == GATED_SUMMARY
    # The model's own wording is still on the record, in the update it belongs to.
    assert proves.summary not in state.assessment.summary


def test_a_rewrite_may_not_restate_a_figure_that_only_the_claim_makes():
    """The report is written after the review, so the number rule is what checks its prose."""
    class Affirming:
        def review(self, state, decisive):
            return ReviewResult(decision="accept", narrowed_status=None, reasons=[])

        def report(self, state, decisive):
            return Report(summary="The filing reports 10% growth against the claimed 90%.",
                          supported_rewrite="The evidence proves a 90% increase.",
                          source_independence="", measurement_limitations=[],
                          interpretation_ambiguity="")

    claim = Claim(id="c", document_id="d", span_id="s0", text="Revenue grew 90%.", start=0, end=17,
                  assertion_type=AssertionType.reported_achievement)
    state = InvestigationState(claim=claim)
    span = SourceSpan(id="s1", document_id="d", kind="paragraph", text="Revenue grew 10%.",
                      start=0, end=17)
    reconcile(state, [_item(1, "s1", "Revenue grew 10%.", Relationship.contradicts)], {})
    state.assessment.status = EvidenceStatus.contradicted
    spans = {"s1": span}
    finding = finalize(state, spans, Affirming(), run_review(state, spans, Affirming()))
    assert finding.evidence_status == EvidenceStatus.contradicted
    # 90 appears only in the claim under test, so nothing establishes it.
    assert finding.supported_rewrite is None
    # A summary may still quote the claim's figure, because it is discussing the claim.
    assert "90" in finding.summary
    # A rewrite built from what the evidence says is kept.
    assert numbers_supported("Revenue grew 10%.", state, spans, quoting_claim=False)


def test_an_abstention_carries_no_overstatement_mechanism():
    """The updater named mechanisms alongside insufficient on the measured runs."""
    state = InvestigationState(claim=_claim())
    named = StateUpdate(status=EvidenceStatus.insufficient,
                        mechanisms=[Mechanism.scope, Mechanism.selective_comparison],
                        summary="The figures are per unit, not a total.", unresolved=[],
                        explanation="e")
    record = apply_update(state, named, [], [], "v")
    assert record.new_status == EvidenceStatus.insufficient
    # The status is what the model asked for, so its own summary is kept.
    assert state.assessment.summary == named.summary
    # A mechanism is a conclusion about the claim, and this status reaches none.
    assert state.assessment.mechanisms == []
