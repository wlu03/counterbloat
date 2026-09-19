from math import log, sqrt

import pytest

from backend.belief.accumulator import (
    EvidenceAccumulator, EvidenceContribution, conditioned_bayes_update, sigmoid,
)
from backend.belief.priority import choose, coverage, critical_open
from backend.models import AnswerStatus, VerificationQuestion


def test_known_bayes_sequence():
    p = conditioned_bayes_update(0.20, 2.0)
    assert p == pytest.approx(1 / 3)
    p = conditioned_bayes_update(p, 6.0)
    assert p == pytest.approx(0.75)
    assert conditioned_bayes_update(p, 1.0) == pytest.approx(0.75)
    assert conditioned_bayes_update(p, 0.25) == pytest.approx(3 / 7)


def test_duplicate_is_idempotent():
    model = EvidenceAccumulator(0.20)
    item = EvidenceContribution("family-a", 1, log(2.0))
    assert model.upsert(item)
    before = model.raw_probability()
    assert not model.upsert(item)
    assert model.raw_probability() == before


def test_revision_replaces_and_withdrawal_recomputes():
    model = EvidenceAccumulator(0.20)
    model.upsert(EvidenceContribution("a", 1, log(2.0)))
    model.upsert(EvidenceContribution("b", 1, log(6.0)))
    assert model.raw_probability() == pytest.approx(0.75)
    model.upsert(EvidenceContribution("b", 2, log(3.0)))
    assert model.raw_probability() == pytest.approx(0.60)
    assert model.withdraw("b") and not model.withdraw("b")
    assert model.raw_probability() == pytest.approx(1 / 3)


def test_tempering():
    assert EvidenceAccumulator(0.20).raw_probability() == pytest.approx(0.20)
    zero = EvidenceAccumulator(0.20, tempering=0.0)
    zero.upsert(EvidenceContribution("a", 1, log(6.0)))
    assert zero.raw_probability() == pytest.approx(0.20)
    half = EvidenceAccumulator(0.20, tempering=0.5)
    half.upsert(EvidenceContribution("a", 1, log(2.0)))
    half.upsert(EvidenceContribution("b", 1, log(6.0)))
    odds = 0.25 * sqrt(12.0)
    assert half.raw_probability() == pytest.approx(odds / (1 + odds))


def test_order_invariance_for_fixed_groups():
    items = [EvidenceContribution("a", 1, log(2.0)), EvidenceContribution("b", 1, log(6.0))]
    left, right = EvidenceAccumulator(0.20), EvidenceAccumulator(0.20)
    for item in items:
        left.upsert(item)
    for item in reversed(items):
        right.upsert(item)
    assert left.raw_probability() == right.raw_probability()


def test_invalid_and_stale_input_is_rejected():
    model = EvidenceAccumulator(0.20)
    model.upsert(EvidenceContribution("a", 2, log(2.0)))
    for bad in (EvidenceContribution("a", 2, log(3.0)), EvidenceContribution("a", 1, log(2.0))):
        with pytest.raises(ValueError):
            model.upsert(bad)
    for factor in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            conditioned_bayes_update(0.20, factor)
    for prior in (0.0, 1.0, -0.1, float("nan")):
        with pytest.raises(ValueError):
            EvidenceAccumulator(prior)
    with pytest.raises(ValueError):
        EvidenceContribution("a", 1, 0.0, weight=1.1)


def test_direction_and_stable_sigmoid():
    assert conditioned_bayes_update(0.20, 2.0) > 0.20 > conditioned_bayes_update(0.20, 0.5)
    assert sigmoid(1000.0) == 1.0 and sigmoid(-1000.0) == 0.0 and sigmoid(0.0) == 0.5


def _q(i, materiality, status=AnswerStatus.open, critical=False):
    return VerificationQuestion(id=f"q{i}", claim_id="c", text=f"question {i}",
                                materiality=materiality, status=status, critical=critical)


def test_priority_prefers_material_open_questions_and_coverage_counts_answers():
    questions = [_q(1, 1), _q(2, 3, critical=True), _q(3, 3, AnswerStatus.answered)]
    assert [q.id for q in choose(questions)] == ["q2", "q1"]
    assert coverage(questions) == pytest.approx(3 / 7)
    assert critical_open(questions) == ["question 2"]
