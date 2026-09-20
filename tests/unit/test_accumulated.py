from backend.assessment import accumulated
from backend.config import AssessmentSettings
from backend.models import AssertionType, Claim, Mode, Relationship, RunManifest
from backend.providers.base import EvidenceScoreDraft

CLAIM = Claim(id="c1", document_id="d", span_id="s", text="Revenue rose to $76.1 million.",
              start=0, end=30, assertion_type=AssertionType.numerical_comparison)

FILED = {"agent": "xbrl-verifier", "tier": "structured", "stance": "contradicts",
         "tag": "Revenues", "accession": "0001-15-1", "note": "filed 80293000 against 76100000"}
PASSAGE = {"agent": "risk-matcher", "tier": "filing_text", "stance": "neutral",
           "quote": "Demand for our product may fall in a downturn.", "accession": "0001-15-1"}
NOTHING = {"agent": "outcome-checker", "tier": "external", "stance": "not_found"}


def test_a_finding_that_found_nothing_is_not_weighed():
    state = accumulated.state_for(CLAIM, [FILED, NOTHING])
    assert len(state.evidence) == 1 and len(state.groups) == 1


def test_the_same_passage_quoted_twice_is_one_group():
    state = accumulated.state_for(CLAIM, [PASSAGE, PASSAGE, FILED])
    assert len(state.evidence) == 3
    assert len(state.groups) == 2
    assert sorted(len(g.member_ids) for g in state.groups) == [1, 2]


def test_each_finding_keeps_what_it_said_about_the_claim():
    state = accumulated.state_for(CLAIM, [FILED, PASSAGE])
    kinds = {e.document_id: e.relationship for e in state.evidence}
    assert kinds["0001-15-1"] in (Relationship.contradicts, Relationship.context)
    assert {e.relationship for e in state.evidence} == {Relationship.contradicts,
                                                        Relationship.context}


def test_every_item_belongs_to_a_group():
    state = accumulated.state_for(CLAIM, [FILED, PASSAGE])
    ids = {g.id for g in state.groups}
    assert all(e.group_id in ids for e in state.evidence)


class Scorer:
    """Stands in for the model that judges how strongly a group bears on the target."""

    def __init__(self, value=1.2):
        self.value = value
        self.seen = 0

    def score_evidence(self, target, claim, evidence, related):
        self.seen += 1
        return EvidenceScoreDraft(log_evidence=self.value,
                                  supporting_evidence_ids=[e.id for e in evidence],
                                  short_basis="stub")


def _manifest():
    return RunManifest(analysis_id="a", mode=Mode.live, config_hash="c")


def test_the_score_rises_above_the_prior_when_evidence_points_that_way():
    belief = accumulated.probability_for(CLAIM, [FILED, PASSAGE], Scorer(1.2), _manifest())
    assert belief is not None and belief.method == "evidence_accumulator"
    assert belief.prior == 0.5 and belief.raw_probability > 0.5


def test_the_score_falls_below_the_prior_when_evidence_points_the_other_way():
    belief = accumulated.probability_for(CLAIM, [FILED, PASSAGE], Scorer(-1.2), _manifest())
    assert belief.raw_probability < 0.5


def test_one_group_is_scored_once_however_often_its_passage_appears():
    scorer = Scorer()
    accumulated.probability_for(CLAIM, [PASSAGE, PASSAGE, PASSAGE], scorer, _manifest())
    assert scorer.seen == 1


def test_nothing_found_yields_no_score():
    assert accumulated.probability_for(CLAIM, [NOTHING], Scorer(), _manifest()) is None
    assert accumulated.probability_for(CLAIM, [], Scorer(), _manifest()) is None


def test_tempering_pulls_the_score_back_towards_the_prior():
    firm = accumulated.probability_for(CLAIM, [FILED], Scorer(2.0), _manifest(),
                                       AssessmentSettings(tempering=1.0))
    damped = accumulated.probability_for(CLAIM, [FILED], Scorer(2.0), _manifest(),
                                         AssessmentSettings(tempering=0.25))
    assert 0.5 < damped.raw_probability < firm.raw_probability
