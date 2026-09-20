import pytest

from backend.assessment import calibration


def _data(n=60, split=0.5):
    """Scores where a high score really does mean the claim was contradicted more often."""
    scores = [i / n for i in range(n)]
    outcomes = [1 if s >= split else 0 for s in scores]
    return scores, outcomes


def test_a_curve_is_refused_when_there_is_little_to_fit_on():
    with pytest.raises(calibration.NotEnoughOutcomes, match="below the 30"):
        calibration.fit([0.1, 0.9], [0, 1])


def test_a_curve_is_refused_when_one_outcome_barely_appears():
    scores = [i / 60 for i in range(60)]
    outcomes = [1 if i > 57 else 0 for i in range(60)]  # only two disagreed
    with pytest.raises(calibration.NotEnoughOutcomes, match="each outcome needs"):
        calibration.fit(scores, outcomes)


def test_a_fitted_curve_reports_what_it_was_fitted_on():
    scores, outcomes = _data()
    fitted = calibration.fit(scores, outcomes)
    assert fitted.n == 60 and fitted.positives == 30 and fitted.base_rate == 0.5
    assert "untested" in fitted.note


def test_a_higher_score_never_gives_a_lower_probability():
    scores, outcomes = _data()
    fitted = calibration.fit(scores, outcomes)
    probabilities = [fitted.probability(s) for s in scores]
    assert all(a <= b for a, b in zip(probabilities, probabilities[1:]))
    assert fitted.probability(0.05) < 0.5 < fitted.probability(0.95)


def test_a_separable_score_calibrates_almost_perfectly():
    fitted = calibration.fit(*_data())
    assert fitted.brier < 0.01


def test_the_reliability_rows_compare_predicted_with_observed():
    rows = calibration.reliability([0.1, 0.1, 0.9, 0.9], [0, 0, 1, 1])
    predicted, observed, count = rows[0]
    assert predicted == pytest.approx(0.1) and observed == 0.0 and count == 2
    predicted, observed, count = rows[-1]
    assert predicted == pytest.approx(0.9) and observed == 1.0 and count == 2


def test_the_score_measures_how_wrong_the_probabilities_were():
    assert calibration.brier([1.0, 0.0], [1, 0]) == 0.0
    assert calibration.brier([0.0, 1.0], [1, 0]) == 1.0
    assert calibration.brier([], []) == 0.0
