import pytest

from backend.assessment.inflation import (
    CONTRADICTS, NOT_FOUND, SUPPORTS, assess, evidence_gap, rhetorical_inflation,
)
from backend.models import AssertionType, Claim


def _claim(text, kind=AssertionType.reported_achievement, **fields):
    return Claim(id="c1", document_id="d", span_id="s", text=text, start=0, end=len(text),
                 assertion_type=kind, **fields)


SPECIFIC = _claim("Revenue was $76.1 million in the first quarter versus a year ago.",
                  kind=AssertionType.numerical_comparison, metric="revenue",
                  value="$76.1 million", unit="USD millions", period="2015-Q1")
VAGUE = _claim("We delivered world-class results.", kind=AssertionType.promotional)


def test_a_vague_superlative_claim_is_more_inflated_than_a_specific_one():
    loud, parts = rhetorical_inflation(VAGUE)
    assert loud == 1.0 and parts["puffery"] == 1.0 and parts["forward_looking"] == 1.0
    assert rhetorical_inflation(SPECIFIC)[0] < 0.2


def test_nothing_found_abstains_rather_than_scoring_zero():
    result = assess(VAGUE, [NOT_FOUND, NOT_FOUND])
    assert result.abstained is True and result.evidence_gap is None
    assert result.rhetorical_inflation == 1.0  # loudness is still measurable
    assert "anything to compare" in result.reason


def test_only_stances_that_looked_at_something_count():
    gap, parts, checked = evidence_gap([CONTRADICTS, NOT_FOUND, NOT_FOUND])
    assert checked == 1 and parts["contradicted_share"] == 1.0 and gap == 1.0


def test_support_closes_the_gap():
    assert evidence_gap([SUPPORTS, SUPPORTS])[0] == 0.0
    assert evidence_gap([SUPPORTS, CONTRADICTS])[0] == 0.5


def test_a_hedging_delta_only_counts_when_the_claim_is_the_firmer_side():
    assert "gap.hedging_delta" not in assess(SPECIFIC, [SUPPORTS], hedging=-2.0).parts
    assert assess(SPECIFIC, [SUPPORTS], hedging=2.5).parts["gap.hedging_delta"] == 0.5


def test_a_hedging_delta_alone_is_enough_to_report_a_gap():
    result = assess(SPECIFIC, [NOT_FOUND], hedging=5.0)
    assert result.abstained is False and result.evidence_gap == 1.0 and result.checked == 0


def test_the_two_axes_are_reported_apart():
    result = assess(VAGUE, [SUPPORTS])
    # Loud wording, and nothing disagreeing with it. Puffery is not a finding.
    assert result.rhetorical_inflation == 1.0 and result.evidence_gap == 0.0


def test_an_agent_that_took_no_side_does_not_dilute_a_contradiction():
    # One filed figure disagrees; three matched passages bear neither way.
    gap, parts, checked = evidence_gap([CONTRADICTS, "neutral", "neutral", "context"])
    assert checked == 1 and gap == 1.0 and parts["contradicted_share"] == 1.0


def test_agents_that_all_took_no_side_leave_nothing_to_divide():
    gap, parts, checked = evidence_gap(["neutral", "context", NOT_FOUND])
    assert gap is None and checked == 0
