"""The three updating strategies, the evidence scorer, and the score ledger."""
from math import log

import pytest

from backend.belief import strategies
from backend.config import AssessmentSettings
from backend.evidence.provenance import merge, reconcile, withdraw
from backend.models import (
    AssertionType, Calculation, Claim, EvidenceItem, EvidenceScore, InvestigationState,
    Relationship,
)
from backend.providers.base import EvidenceScoreDraft, ProviderError
from tests.fakes import FakeLLM


def _state():
    claim = Claim(id="c", document_id="d", span_id="s0", text="Emissions fell 40%.", start=0, end=19,
                  assertion_type=AssertionType.reported_achievement)
    return InvestigationState(claim=claim, target=strategies.new_target(claim, None))


def _item(i, quote):
    return EvidenceItem(id=f"e{i}", claim_id="c", span_id=f"s{i}", document_id="d", quote=quote,
                        relationship=Relationship.supports, target="claim")


def _score(state, group_index, factor, version=None):
    group = state.groups[group_index]
    return EvidenceScore(group_id=group.id, group_version=version or group.version,
                         log_evidence=log(factor), method="validated_observation_model",
                         supporting_evidence_ids=[], short_basis="synthetic factor",
                         conditioning_context_hash="fixture", scorer_version="fixture")


def test_numerical_mechanics_fixture():
    """Synthetic factors. This checks arithmetic and ledger behaviour, not any real evidence."""
    settings = AssessmentSettings(updater="evidence_accumulator", prior=0.20)
    state = _state()
    assert strategies.accumulate(state, settings).raw_probability == pytest.approx(0.20)
    reconcile(state, [_item(1, "Observation A.")], {})
    state.scores = [_score(state, 0, 2)]
    assert strategies.accumulate(state, settings).raw_probability == pytest.approx(1 / 3)
    reconcile(state, [_item(2, "Observation B.")], {})
    state.scores.append(_score(state, 1, 6))
    assert strategies.accumulate(state, settings).raw_probability == pytest.approx(0.75)
    reconcile(state, [_item(3, "Observation B.")], {})  # the same observation from another page
    assert len(state.groups) == 2
    assert strategies.accumulate(state, settings).raw_probability == pytest.approx(0.75)
    state.scores[1] = _score(state, 1, 3)               # B's factor is replaced, not added
    assert strategies.accumulate(state, settings).raw_probability == pytest.approx(0.60)
    withdraw(state, "e2")
    withdraw(state, "e3")                               # B has no members left
    assert strategies.accumulate(state, settings).raw_probability == pytest.approx(1 / 3)


def test_a_score_for_an_older_group_version_is_not_used():
    settings = AssessmentSettings(updater="evidence_accumulator", prior=0.20)
    state = _state()
    reconcile(state, [_item(1, "A."), _item(2, "B.")], {})
    state.scores = [_score(state, 0, 2), _score(state, 1, 6)]
    merge(state, state.groups[0].id, state.groups[1].id)  # they were one observation
    belief = strategies.accumulate(state, settings)
    assert belief.raw_probability == pytest.approx(0.20) and belief.contributions == []
    assert [g.active for g in state.groups] == [True, False]
    assert "merged" in state.groups[0].history[0]


def test_groups_are_scored_once_per_context_and_again_when_it_changes():
    llm, failures = FakeLLM(), []
    state = _state()
    reconcile(state, [_item(1, "A."), _item(2, "B.")], {})
    strategies.score_groups(state, llm, failures)
    strategies.score_groups(state, llm, failures)
    assert llm.score_calls == 2 and len(state.scores) == 2       # the second pass used the stored scores
    calc = Calculation(id="n", claim_id="c", inputs=[], steps=[], outputs={}, units={},
                       lineage=[state.groups[0].id], claim_relation="disagrees")
    state.calculations.append(calc)                                # new context for group 0 only
    strategies.score_groups(state, llm, failures)
    assert llm.score_calls == 3
    assert [s.log_evidence for s in state.scores] == [1.5, 0.25]


def test_unavailable_and_invalid_scores_add_nothing():
    class Broken(FakeLLM):
        def score_evidence(self, target, claim, evidence, calculations):
            if evidence[0].quote == "A.":
                raise ProviderError("openai score failed: 503")
            return EvidenceScoreDraft(log_evidence=float("inf"), supporting_evidence_ids=[],
                                      short_basis="")

    state, failures = _state(), []
    reconcile(state, [_item(1, "A."), _item(2, "B.")], {})
    strategies.score_groups(state, Broken(), failures)
    settings = AssessmentSettings(updater="evidence_accumulator", prior=0.3)
    assert state.scores == [] and len(failures) == 2
    assert strategies.accumulate(state, settings).raw_probability == pytest.approx(0.3)


def test_withdrawal_removes_the_calculation_that_depended_on_the_group():
    state = _state()
    reconcile(state, [_item(1, "A."), _item(2, "B.")], {})
    state.calculations = [Calculation(id="n", claim_id="c", inputs=[], steps=[], outputs={},
                                      units={}, lineage=[state.groups[1].id])]
    withdraw(state, "e2")
    assert state.calculations == [] and "withdrawn" in state.groups[1].history[0]


def test_changing_the_target_or_claim_changes_the_scoring_context():
    state = _state()
    reconcile(state, [_item(1, "A.")], {})
    members = state.evidence
    base = strategies.context_hash(state.target, state.claim, members, [])
    other_target = state.target.model_copy(update={"id": "averitec-refuted-vs-supported"})
    reworded = state.claim.model_copy(update={"text": "Emissions per unit fell 40%.", "version": 2})
    assert strategies.context_hash(other_target, state.claim, members, []) != base
    assert strategies.context_hash(state.target, reworded, members, []) != base
