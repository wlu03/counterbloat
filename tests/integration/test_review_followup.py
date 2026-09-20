"""Defects found by reviewing the follow-up after a reviewer asks for a check."""
from backend.config import Retrieval, Settings
from backend.ingestion.snapshot import admit
from backend.models import BeliefUpdate, EvidenceStatus, Finding, InvestigationState, Mechanism, Mode
from backend.orchestration.worker import Deps, run_analysis
from backend.providers.base import ProviderError, QuestionDraft, Report, ReviewResult
from backend.retrieval.memory import MemoryIndex
from tests.fakes import REPORT, FakeLLM

CHECK = "Confirm the organisational boundary of the inventory."


def _asks_once(reason=CHECK, then="accept", narrowed=None):
    class Reviewer(FakeLLM):
        reviews = 0

        def review(self, state, decisive):
            Reviewer.reviews += 1
            if Reviewer.reviews == 1:
                return ReviewResult(decision="request_check", narrowed_status=None, reasons=[reason])
            return ReviewResult(decision=then, narrowed_status=narrowed, reasons=[])
    return Reviewer


def _run(store, llm, index=None, retrieval=None, **settings):
    deps = Deps(store=store, index=index or MemoryIndex(), llm_factory=llm,
                settings=Settings(mode=Mode.frozen, retrieval=retrieval or Retrieval(),
                                  **settings))
    snapshot, spans = admit(store, REPORT, "text/html")
    deps.index.index(snapshot, spans)
    store.put("analyses", "an-1", {"id": "an-1", "document_id": snapshot.id, "status": "queued"},
              document_id=snapshot.id)
    run_analysis("an-1", deps)
    return store.get("analyses", "an-1"), store.find("findings", Finding, analysis_id="an-1")


def test_a_cancel_during_the_follow_up_stops_the_job_before_the_report(store):
    calls = []

    class Cancelling(_asks_once()):
        def review(self, state, decisive):
            job = store.get("analyses", "an-1")
            job["cancel_requested"] = True
            store.update("analyses", "an-1", job)
            return super().review(state, decisive)

        def report(self, state, decisive):
            calls.append("report")
            return super().report(state, decisive)

    job, findings = _run(store, Cancelling)
    assert job["status"] == "cancelled" and job["partial"] is True
    assert findings == [] and calls == [] and Cancelling.reviews == 1


def test_a_cancelled_claim_keeps_the_rows_its_update_refers_to(store):
    class Cancelling(FakeLLM):
        def update_state(self, state, new_evidence_ids, new_calculation_ids):
            job = store.get("analyses", "an-1")
            job["cancel_requested"] = True
            store.update("analyses", "an-1", job)
            return super().update_state(state, new_evidence_ids, new_calculation_ids)

    job, _ = _run(store, Cancelling)
    [state] = store.find("states", InvestigationState, analysis_id="an-1")
    [update] = store.find("updates", BeliefUpdate, claim_id=state.claim.id)
    assert job["status"] == "cancelled"
    assert all(store.get("evidence", i) for i in update.changed_evidence_ids)
    assert all(store.get("calculations", i) for i in update.changed_calculation_ids)


def test_the_follow_up_retries_an_update_that_failed(store):
    class FailsOnce(_asks_once()):
        failed = False

        def update_state(self, state, new_evidence_ids, new_calculation_ids):
            if not FailsOnce.failed:
                FailsOnce.failed = True
                raise ProviderError("openai update failed: 503")
            return super().update_state(state, new_evidence_ids, new_calculation_ids)

    job, [finding] = _run(store, FailsOnce)
    [state] = store.find("states", InvestigationState, analysis_id="an-1")
    assert state.version == 1 and finding.evidence_status == EvidenceStatus.contradicted
    assert job["partial"] is True  # the failed call is still reported


def test_the_requested_check_is_searched_for_before_other_open_questions(store):
    queries = []

    class Recording(MemoryIndex):
        def search(self, query, **options):
            queries.append(query)
            return super().search(query, **options)

    class ManyQuestions(_asks_once()):
        def plan_questions(self, claim, checklist, task=""):
            return [QuestionDraft(text=f"Planned question {i}?", why_it_matters="", evidence_needed="",
                                  materiality=3, answerability=3, critical=False) for i in range(4)]

    _run(store, ManyQuestions, index=Recording(), retrieval=Retrieval(show_whole_corpus_under=0))
    assert any(CHECK in q for q in queries)


def test_a_requested_check_with_an_unsupported_number_is_not_repeated_in_the_finding(store):
    invented = "Check the 73% scope 3 share reported in 2019."
    _, [finding] = _run(store, _asks_once(invented))
    [state] = store.find("states", InvestigationState, analysis_id="an-1")
    assert all("73" not in q.text for q in state.questions)
    assert all("73" not in q for q in finding.uncertainty.critical_missing_questions)


def test_an_open_requested_check_is_listed_once(store):
    class AlwaysAsks(FakeLLM):
        def review(self, state, decisive):
            return ReviewResult(decision="request_check", narrowed_status=None, reasons=[CHECK])

    _, [finding] = _run(store, AlwaysAsks)
    assert sum(CHECK in q for q in finding.uncertainty.critical_missing_questions) == 1


def test_a_narrowed_verdict_drops_the_mechanisms_and_text_of_the_earlier_one(store):
    class Narrows(FakeLLM):
        def review(self, state, decisive):
            return ReviewResult(decision="narrow", narrowed_status="insufficient", reasons=["weak"])

        def report(self, state, decisive):
            return Report(summary="A 77% share was found.", supported_rewrite=None,
                          source_independence="", measurement_limitations=[],
                          interpretation_ambiguity="")

    _, [finding] = _run(store, Narrows)
    assert finding.evidence_status == EvidenceStatus.insufficient and finding.mechanisms == []
    assert finding.summary == "Assessment: insufficient. See the evidence and calculations."
    assert Mechanism.scope not in finding.mechanisms


def test_one_keyword_only_search_marks_the_whole_analysis(store):
    class Flaky(MemoryIndex):
        searches = 0

        def search(self, query, **options):
            Flaky.searches += 1
            self.used_embeddings = Flaky.searches != 2  # only the second search lacks vectors
            return super().search(query, **options)

    _run(store, FakeLLM, index=Flaky(), retrieval=Retrieval(show_whole_corpus_under=0))
    assert Flaky.searches > 2 and store.get("manifests", "an-1")["embedding_search"] is False
