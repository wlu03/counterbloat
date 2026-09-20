"""The three updating strategies, the evidence scorer, and the score ledger."""
from math import log

import pytest

from backend.belief import strategies
from backend.config import AssessmentSettings
from backend.evidence.provenance import merge, reconcile, withdraw
from backend.models import (
    AssertionType, Calculation, Claim, EvidenceItem, EvidenceScore, InvestigationState, Mode,
    Relationship, RunManifest,
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


def _manifest():
    return RunManifest(analysis_id="t", mode=Mode.frozen, config_hash="")


def test_a_score_for_an_older_group_version_is_not_used():
    settings = AssessmentSettings(updater="evidence_accumulator", prior=0.20)
    state = _state()
    reconcile(state, [_item(1, "A."), _item(2, "B.")], {})
    state.scores = [_score(state, 0, 2), _score(state, 1, 6)]
    merge(state, state.groups[0].id, state.groups[1].id)  # they were one observation
    belief = strategies.accumulate(state, settings)
    # The merged unit is active and now has no score that applies to it. A number built from
    # what is left would stand for a unit that was never scored, so there is no number.
    assert belief.raw_probability is None and belief.contributions == []
    assert belief.calibration_status == "incomplete"
    assert [g.active for g in state.groups] == [True, False]
    assert "merged" in state.groups[0].history[0]


def test_groups_are_scored_once_per_context_and_again_when_it_changes():
    llm, failures = FakeLLM(), _manifest()
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
    assert {s.group_id: s.log_evidence for s in state.scores} == {state.groups[0].id: 1.5,
                                                                  state.groups[1].id: 0.25}


def test_groups_that_feed_one_calculation_are_scored_together_and_count_once():
    llm, state = FakeLLM(), _state()
    reconcile(state, [_item(1, "A."), _item(2, "B."), _item(3, "C.")], {})
    a, b, c = (g.id for g in state.groups)
    state.calculations.append(Calculation(id="n", claim_id="c", inputs=[], steps=[], outputs={},
                                          units={}, lineage=[a, b], claim_relation="disagrees"))
    strategies.score_groups(state, llm, _manifest())
    assert llm.score_calls == 2
    assert {s.group_id: s.log_evidence for s in state.scores} == {"+".join(sorted([a, b])): 1.5, c: 0.25}
    settings = AssessmentSettings(updater="evidence_accumulator", prior=0.5)
    assert strategies.accumulate(state, settings).raw_logit == pytest.approx(1.75)
    withdraw(state, "e2")  # the calculation loses an input group, so the joined score no longer applies
    # Group a is active again on its own and unscored, so the ledger is incomplete until it is
    # scored. Reporting c's 0.25 alone would leave a out of a number that claims to include it.
    assert strategies.accumulate(state, settings).raw_logit is None
    strategies.score_groups(state, llm, _manifest())
    assert strategies.accumulate(state, settings).raw_logit == pytest.approx(0.5)


def test_unavailable_and_invalid_scores_add_nothing():
    class Broken(FakeLLM):
        def score_evidence(self, target, claim, evidence, calculations):
            if evidence[0].quote == "A.":
                raise ProviderError("openai score failed: 503")
            return EvidenceScoreDraft(log_evidence=float("inf"), supporting_evidence_ids=[],
                                      short_basis="")

    state, failures = _state(), _manifest()
    reconcile(state, [_item(1, "A."), _item(2, "B.")], {})
    strategies.score_groups(state, Broken(), failures)
    settings = AssessmentSettings(updater="evidence_accumulator", prior=0.3)
    assert state.scores == []
    assert len(failures.errors) == 1 and len(failures.rejections) == 1
    # Neither unit could be scored. Falling back to the prior would report a provider outage as
    # a finding about the claim.
    belief = strategies.accumulate(state, settings)
    assert belief.raw_probability is None and belief.calibration_status == "incomplete"


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


def test_a_score_is_not_reused_for_another_target_or_scorer_version(monkeypatch):
    llm, state = FakeLLM(), _state()
    reconcile(state, [_item(1, "A.")], {})
    strategies.score_groups(state, llm, _manifest())
    state.target = state.target.model_copy(update={"id": "averitec-refuted"})
    strategies.score_groups(state, llm, _manifest())
    assert llm.score_calls == 2
    monkeypatch.setattr(strategies, "SCORER_VERSION", "llm-scorer-next")
    strategies.score_groups(state, llm, _manifest())
    assert llm.score_calls == 3 and state.scores[0].scorer_version == "llm-scorer-next"


def test_the_updater_status_is_the_one_its_samples_agree_on():
    from backend.models import EvidenceStatus
    from backend.providers.base import StateUpdate

    class Wavering(FakeLLM):
        def __init__(self, statuses):
            super().__init__()
            self.statuses, self.asked = list(statuses), 0

        def update_state(self, state, new_evidence_ids, new_calculation_ids):
            status = self.statuses[self.asked]
            self.asked += 1
            return StateUpdate(status=status, mechanisms=[], summary=f"sample {self.asked}",
                               unresolved=[], explanation="")

    state = _state()
    settings = AssessmentSettings(updater="linguistic", updater_samples=3)
    llm = Wavering(["insufficient", "contradicted", "contradicted"])
    update, _ = strategies.run(state, [], [], llm, settings, _manifest())
    # Two of the three samples agree, and the summary comes from the sample that said so.
    assert update.status == EvidenceStatus.contradicted and update.summary == "sample 2"
    assert llm.asked == 3

    # With one sample the updater is asked once and its answer is used as it is.
    llm = Wavering(["insufficient"])
    update, _ = strategies.run(state, [], [], llm, AssessmentSettings(updater="linguistic"), _manifest())
    assert update.status == EvidenceStatus.insufficient and llm.asked == 1

    # No majority: the earliest status is kept, so the result is still a whole sample.
    llm = Wavering(["mixed", "contradicted", "supported"])
    update, _ = strategies.run(state, [], [], llm, settings, _manifest())
    assert update.status == EvidenceStatus.mixed and update.summary == "sample 1"


def test_a_second_copy_of_a_passage_is_not_a_second_observation_to_score():
    llm, state = FakeLLM(), _state()
    reconcile(state, [_item(1, "Emissions fell 40% at the bottle plant.")], {})
    strategies.score_groups(state, llm, _manifest())
    assert llm.score_calls == 1
    # The same passage found again on another page joins the same group. Scoring it a second
    # time would read one observation twice.
    reconcile(state, [_item(2, "Emissions fell 40% at the bottle plant.")], {})
    strategies.score_groups(state, llm, _manifest())
    assert llm.score_calls == 1 and len(state.scores) == 1


def test_a_score_that_names_no_admitted_evidence_is_not_used():
    class Uncited(FakeLLM):
        def score_evidence(self, target, claim, evidence, calculations):
            return EvidenceScoreDraft(log_evidence=2.0, short_basis="",
                                      supporting_evidence_ids=["e-does-not-exist"])

    state, manifest = _state(), _manifest()
    reconcile(state, [_item(1, "A.")], {})
    strategies.score_groups(state, Uncited(), manifest)
    assert state.scores == []
    assert any("cites no admitted evidence" in r for r in manifest.rejections)


def test_changing_the_target_or_the_prior_is_a_new_decision():
    settings = AssessmentSettings(updater="evidence_accumulator", prior=0.5)
    state = _state()
    reconcile(state, [_item(1, "A.")], {})
    base = strategies.input_hash(state, settings, "model-v1")
    assert strategies.input_hash(state, settings, "model-v2") != base
    assert strategies.input_hash(state, settings.model_copy(update={"prior": 0.05}),
                                 "model-v1") != base
    assert strategies.input_hash(state, settings.model_copy(update={"tempering": 0.1}),
                                 "model-v1") != base
    assert strategies.input_hash(state, settings.model_copy(update={"updater_samples": 3}),
                                 "model-v1") != base
    other = state.model_copy(update={"target": state.target.model_copy(
        update={"id": "other-rubric", "hypothesis": "a different question"})})
    assert strategies.input_hash(other, settings, "model-v1") != base
    # The same inputs still give the same hash, so a retry records no second update.
    assert strategies.input_hash(state, settings, "model-v1") == base
