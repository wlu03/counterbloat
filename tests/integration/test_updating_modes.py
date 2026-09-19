"""Each updating strategy run through the real worker with the scripted provider."""
import pytest

from backend.config import AssessmentSettings, Settings
from backend.ingestion.snapshot import admit
from backend.models import BeliefUpdate, EvidenceStatus, Finding, InvestigationState, Mode
from backend.orchestration.worker import Deps, run_analysis
from backend.providers.base import EvidenceAnalysis, Report, ReviewResult
from backend.retrieval.memory import MemoryIndex
from tests.fakes import ARTICLE, REPORT, FakeLLM


def _run(store, updater, llm=FakeLLM, contents=(REPORT,), **settings):
    deps = Deps(store=store, index=MemoryIndex(), llm_factory=llm,
                settings=Settings(mode=Mode.frozen, assessment=AssessmentSettings(updater=updater),
                                  **settings))
    first = None
    for content in contents:
        snapshot, spans = admit(store, content, "text/html")
        deps.index.index(snapshot, spans)
        first = first or snapshot
    store.put("analyses", "an-1", {"id": "an-1", "document_id": first.id, "status": "queued"},
              document_id=first.id)
    run_analysis("an-1", deps)
    [finding] = store.find("findings", Finding, analysis_id="an-1")
    [state] = store.find("states", InvestigationState, analysis_id="an-1")
    return finding, state, store.find("updates", BeliefUpdate, claim_id=state.claim.id)


def test_accumulator_mode_stores_an_internal_score_and_no_public_probability(store):
    finding, state, updates = _run(store, "evidence_accumulator")
    assert finding.evidence_status == EvidenceStatus.contradicted
    assert finding.probability is None and finding.probability_status == "not_calibrated_for_this_target"
    belief = state.belief
    assert belief.method == "evidence_accumulator" and belief.calibration_status == "uncalibrated"
    assert belief.target_id == state.target.id == "material-overstatement-v1"
    assert 0.5 < belief.raw_probability < 1 and belief.calibrated_probability is None
    assert {c.group_id for c in belief.contributions} == {g.id for g in state.groups if g.active}
    assert all(c.method == "llm_estimated" for c in belief.contributions)
    [update] = updates
    assert update.strategy == "evidence_accumulator" and update.input_state_hash
    assert update.previous_score is None and update.new_score == belief.raw_probability
    assert store.get("manifests", "an-1")["updater"] == "evidence_accumulator"


def test_repeated_articles_do_not_raise_the_score(store):
    alone = _run(store, "evidence_accumulator")[1].belief.raw_probability
    repeated = _run(store, "evidence_accumulator", contents=(REPORT, ARTICLE))[1].belief
    assert repeated.raw_probability == pytest.approx(alone)


def test_full_context_mode_is_not_shown_the_previous_assessment(store):
    shown = {}

    class Recording(FakeLLM):
        def reassess(self, target, claim, evidence, calculations, questions):
            shown["evidence_groups"] = [e.group_id for e in evidence]
            shown["arguments"] = (target.id, len(calculations))
            return super().reassess(target, claim, evidence, calculations, questions)

        def update_state(self, *args):
            raise AssertionError("full_context must not call the stateful updater")

    finding, state, [update] = _run(store, "full_context", llm=Recording)
    assert finding.evidence_status == EvidenceStatus.contradicted and finding.probability is None
    assert len(shown["evidence_groups"]) == len(set(shown["evidence_groups"]))  # one per group
    assert shown["arguments"] == ("material-overstatement-v1", 1)
    assert state.belief.method == "full_context" and state.belief.raw_probability == 0.9
    assert state.belief.prior is None and update.strategy == "full_context"


def test_linguistic_mode_reports_no_score(store):
    _, state, [update] = _run(store, "linguistic")
    assert state.belief is None and update.new_score is None


def test_a_requested_check_gets_bounded_follow_up_and_the_report_uses_the_reviewed_verdict(store):
    class Reviewer(FakeLLM):
        reviews = 0

        def review(self, state, decisive):
            Reviewer.reviews += 1
            if Reviewer.reviews == 1:
                return ReviewResult(decision="request_check", narrowed_status=None,
                                    reasons=["Confirm which emissions components are included."])
            return ReviewResult(decision="narrow", narrowed_status="mixed", reasons=["narrowed"])

        def report(self, state, decisive):
            return Report(summary=f"Reported as {state.assessment.status}.", supported_rewrite=None,
                          source_independence="", measurement_limitations=[],
                          interpretation_ambiguity="")

    finding, state, _ = _run(store, "linguistic", llm=Reviewer)
    assert Reviewer.reviews == 2
    assert any(q.why_it_matters == "requested by review" for q in state.questions)
    assert finding.evidence_status == EvidenceStatus.mixed
    assert finding.summary == "Reported as mixed."


def test_an_unfinished_requested_check_stays_visible(store):
    class AlwaysAsks(FakeLLM):
        def review(self, state, decisive):
            return ReviewResult(decision="request_check", narrowed_status=None,
                                reasons=["Confirm the organisational boundary."])

    finding, _, _ = _run(store, "linguistic", llm=AlwaysAsks, max_follow_up_rounds=0)
    assert finding.review_status == "draft"
    assert any("Confirm the organisational boundary." in q
               for q in finding.uncertainty.critical_missing_questions)


def test_a_source_published_after_the_cutoff_is_not_used(store):
    from datetime import UTC, datetime

    shown = []

    class Recording(FakeLLM):
        def analyze_evidence(self, claim, questions, context):
            shown.append(context)
            if "per unit" not in context:
                return EvidenceAnalysis(judgments=[], programs=[], answers=[])
            return super().analyze_evidence(claim, questions, context)

    deps = Deps(store=store, index=MemoryIndex(), llm_factory=Recording,
                settings=Settings(mode=Mode.replay))
    claim_page = b"<html><body><p>We reduced our total operational emissions by 40% in 2025 " \
                 b"compared with 2024.</p></body></html>"
    early, spans = admit(store, claim_page, "text/html", published_at=datetime(2026, 1, 1, tzinfo=UTC))
    deps.index.index(early, spans)
    late, spans = admit(store, REPORT, "text/html", published_at=datetime(2026, 6, 1, tzinfo=UTC))
    deps.index.index(late, spans)
    store.put("analyses", "an-1", {"id": "an-1", "document_id": early.id, "status": "queued",
                                   "mode": "replay", "cutoff": "2026-03-01T00:00:00+00:00"},
              document_id=early.id)
    run_analysis("an-1", deps)
    [finding] = store.find("findings", Finding, analysis_id="an-1")
    [state] = store.find("states", InvestigationState, analysis_id="an-1")
    assert finding.evidence_status == EvidenceStatus.insufficient and finding.evidence_ids == []
    assert shown and all("units produced" not in context for context in shown)
    assert state.evidence == [] and state.calculations == []
    assert state.target.cutoff == datetime(2026, 3, 1, tzinfo=UTC)
