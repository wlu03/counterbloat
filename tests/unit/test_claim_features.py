import pytest

from backend.claims.features import AXES, puffery_density, specificity, specificity_score
from backend.models import AssertionType, Claim


def _claim(text, **fields):
    return Claim(id="c", document_id="d", span_id="s", text=text, start=0, end=len(text),
                 assertion_type=AssertionType.reported_achievement, **fields)


def test_a_fully_specified_claim_scores_every_axis():
    claim = _claim("Net revenues rose to $76.1 million in the second quarter, up from a year ago, "
                   "as verified by our auditor.",
                   metric="net revenues", value="$76.1 million", unit="USD millions",
                   period="2015-Q2")
    assert specificity(claim) == dict.fromkeys(AXES, True)
    assert specificity_score(claim) == 6


def test_an_unspecified_claim_scores_nothing():
    claim = _claim("We had a good stretch and feel confident about where things are heading.")
    assert specificity_score(claim) == 0


def test_a_baseline_is_recognised_from_the_wording_alone():
    assert specificity(_claim("Margins improved versus last year."))["baseline"] is True
    assert specificity(_claim("Margins improved."))["baseline"] is False


def test_a_date_counts_whether_it_is_recorded_or_only_spoken():
    assert specificity(_claim("Revenue grew in the fourth quarter."))["date"] is True
    assert specificity(_claim("Revenue grew.", period="2015-Q2"))["date"] is True
    assert specificity(_claim("Revenue grew."))["date"] is False


@pytest.mark.parametrize("text,expected", [
    ("Revenue rose 13% to $10.3 million.", 0.0),
    ("We delivered world-class execution and outstanding results.", pytest.approx(28.57, abs=0.1)),
])
def test_puffery_is_counted_per_hundred_words(text, expected):
    assert puffery_density(text) == expected


def test_a_measured_superlative_still_counts_as_puffery():
    # The wording is checkable only if the comparison is stated, which the density does not judge.
    assert puffery_density("It was our strongest quarter.") > 0
    assert puffery_density("") == 0.0
