"""A stored investigation is exported, replayed under every strategy, and compared across variants."""
from pathlib import Path

import pytest

from backend.config import AssessmentSettings, Settings
from backend.ingestion.snapshot import admit
from backend.models import EvidenceStatus, InvestigationState, Mode, Relationship, RunManifest
from backend.orchestration.worker import Deps, run_analysis
from backend.retrieval.memory import MemoryIndex
from evaluation.replay.run import STRATEGIES, replay, run_all
from evaluation.replay.scripted import ScriptedLLM
from evaluation.replay.trace import Event, Trace, export_trace
from tests.fakes import ARTICLE, REPORT, FakeLLM

FIXTURES = Path("evaluation/fixtures")


def _manifest():
    return RunManifest(analysis_id="t", mode=Mode.replay, config_hash="")


def _accumulator(trace, prior):
    settings = AssessmentSettings(updater="evidence_accumulator", prior=prior)
    return replay(trace, settings, ScriptedLLM(trace.scripted_scores), _manifest())


def test_mechanics_fixture_replays_to_the_expected_scores():
    trace = Trace.model_validate_json((FIXTURES / "mechanics.json").read_text())
    result = _accumulator(trace, 0.20)
    assert [s["score"] for s in result["steps"]] == pytest.approx([1 / 3, 0.75, 0.75, 0.75, 0.60, 1 / 3])
    # The repeated observation is admitted without an update. Removing the copy leaves the input
    # of the last update unchanged, so that step records no update either.
    assert [s["updated"] for s in result["steps"]] == [True, True, False, False, True, True]


def test_a_stored_investigation_survives_export_and_replay(store):
    deps = Deps(store=store, index=MemoryIndex(), llm_factory=FakeLLM, settings=Settings(
        mode=Mode.frozen, assessment=AssessmentSettings(updater="evidence_accumulator")))
    first = None
    for content in (REPORT, ARTICLE):
        snapshot, spans = admit(store, content, "text/html")
        deps.index.index(snapshot, spans)
        first = first or snapshot
    store.put("analyses", "an-1", {"id": "an-1", "document_id": first.id, "status": "queued"},
              document_id=first.id)
    run_analysis("an-1", deps)
    [state] = store.find("states", InvestigationState, analysis_id="an-1")
    trace = Trace.model_validate_json(export_trace(store, "an-1", state.claim.id).model_dump_json())
    assert [e.kind for e in trace.events].count("calculate") == 1
    for name in STRATEGIES:
        result = replay(trace, AssessmentSettings(updater=name), FakeLLM(), _manifest())
        assert result["final_status"] == EvidenceStatus.contradicted
    assert result["final_score"] == pytest.approx(state.belief.raw_probability)


def test_order_and_repetition_do_not_move_the_accumulator():
    trace = Trace.model_validate_json((FIXTURES / "emissions.json").read_text())
    result = run_all(trace, STRATEGIES, "scripted", seed=7, permutations=4, max_calls=0,
                     prior=0.5, tempering=1.0)
    assert result["seed"] == 7 and result["paid_calls_used"] == 0
    for name in STRATEGIES:
        comparison = result["strategies"][name]["comparison"]
        assert comparison["order_changes_status"] is False
        assert comparison["duplicate_event"]["extra_updates"] == 0
        assert comparison["duplicate_source"]["status_changed"] is False
    runs = result["strategies"]["evidence_accumulator"]["runs"]
    assert {r["active_groups"] for n, r in runs.items() if n.startswith("permutation")} == {3}
    comparison = result["strategies"]["evidence_accumulator"]["comparison"]
    assert comparison["order_score_range"] == pytest.approx(0)
    assert comparison["duplicate_source"]["score_change"] == pytest.approx(0)
    # The unrelated passage has no recorded score, so it abstains and the score stays put.
    assert comparison["irrelevant_addition"]["score_change"] == pytest.approx(0)
    # Scores exist only where the strategy produces them. Elsewhere they are reported as missing.
    assert result["strategies"]["linguistic"]["comparison"]["order_score_range"] is None


def test_removing_the_only_support_leaves_the_claim_unresolved_at_the_prior():
    base = Trace.model_validate_json((FIXTURES / "mechanics.json").read_text())
    only = base.events[0].evidence.model_copy(update={"relationship": Relationship.supports})
    trace = base.model_copy(update={"events": [Event(kind="admit", evidence=only),
                                               Event(kind="withdraw", evidence_id=only.id)]})
    result = _accumulator(trace, 0.3)
    assert [s["status"] for s in result["steps"]] == [EvidenceStatus.supported,
                                                      EvidenceStatus.insufficient]
    assert result["final_score"] == pytest.approx(0.3)


def test_evidence_without_a_usable_score_does_not_count_against_the_claim():
    base = Trace.model_validate_json((FIXTURES / "mechanics.json").read_text())
    trace = base.model_copy(update={"events": base.events[:1], "scripted_scores": {}})
    result = _accumulator(trace, 0.3)
    assert result["final_score"] == pytest.approx(0.3)
    assert "no recorded score" in result["errors"][0]
