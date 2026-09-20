"""Regression tests for defects found by running hostile inputs through the API."""
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.config import AssessmentSettings, Settings
from backend.ingestion.snapshot import admit
from backend.models import Mode, SourceSpan
from backend.orchestration.worker import Deps, run_analysis
from backend.providers.base import ProviderError
from backend.retrieval.memory import MemoryIndex
from tests.fakes import REPORT, FakeLLM

HEADERS = {"X-API-Key": "k"}


def _client(store, monkeypatch, llm=FakeLLM):
    monkeypatch.setenv("COUNTERCHECK_API_KEY", "k")
    deps = Deps(store=store, index=MemoryIndex(), settings=Settings(mode=Mode.frozen), llm_factory=llm)
    return TestClient(create_app(deps))


def test_dates_without_an_offset_and_unknown_values_are_refused(store, monkeypatch):
    client = _client(store, monkeypatch)
    body = {"content": REPORT.decode()}
    assert client.post("/documents", json={**body, "published_at": "2024-01-01T00:00:00"},
                       headers=HEADERS).status_code == 422
    assert client.post("/documents", json={**body, "media_type": "image/png"},
                       headers=HEADERS).status_code == 422
    document = client.post("/documents", json={**body, "published_at": "2024-01-01T00:00:00Z"},
                           headers=HEADERS).json()
    assert client.post("/analyses", json={"document_id": document["id"], "cutoff": "2025-01-01"},
                       headers=HEADERS).status_code == 422
    assert client.get("/claims/unknown/updates", headers=HEADERS).status_code == 404


def test_idempotency_key_reuse_for_another_document_is_a_conflict(store, monkeypatch):
    client = _client(store, monkeypatch)
    first = client.post("/documents", json={"content": REPORT.decode()}, headers=HEADERS).json()
    second = client.post("/documents", json={"content": "<p>Other.</p>"}, headers=HEADERS).json()
    keyed = {**HEADERS, "Idempotency-Key": "once"}
    assert client.post("/analyses", json={"document_id": first["id"]}, headers=keyed).status_code == 200
    assert client.post("/analyses", json={"document_id": second["id"]}, headers=keyed).status_code == 409


def test_a_misspelled_review_decision_is_refused(store, monkeypatch):
    client = _client(store, monkeypatch)
    document = client.post("/documents", json={"content": REPORT.decode()}, headers=HEADERS).json()
    job = client.post("/analyses", json={"document_id": document["id"]}, headers=HEADERS).json()
    [finding] = client.get(f"/analyses/{job['id']}/findings", headers=HEADERS).json()
    url = f"/findings/{finding['finding_id']}/review"
    assert client.post(url, json={"reviewer": "a", "decision": "rejected"}, headers=HEADERS).status_code == 422
    rejected = client.post(url, json={"reviewer": "a", "decision": "reject"}, headers=HEADERS).json()
    assert rejected["review_status"] == "blocked"


def test_second_upload_with_another_media_type_keeps_the_stored_passages(store):
    first, spans = admit(store, REPORT, "text/html")
    again, _ = admit(store, REPORT, "text/plain")
    assert again.media_type == "text/html"
    assert [s.id for s in store.find("spans", SourceSpan, document_id=first.id)] == [s.id for s in spans]


def test_a_failed_review_call_makes_the_job_partial(store):
    class ReviewDown(FakeLLM):
        def review(self, state, decisive):
            raise ProviderError("openai review failed: 503")

    deps = Deps(store=store, index=MemoryIndex(), settings=Settings(mode=Mode.frozen),
                llm_factory=ReviewDown)
    snapshot, spans = admit(store, REPORT, "text/html")
    deps.index.index(snapshot, spans)
    store.put("analyses", "an-1", {"id": "an-1", "document_id": snapshot.id, "status": "queued"},
              document_id=snapshot.id)
    run_analysis("an-1", deps)
    job = store.get("analyses", "an-1")
    assert job["status"] == "complete" and job["partial"] is True
    assert "503" in store.get("manifests", "an-1")["errors"][0]


def test_internal_scores_are_served_only_by_the_research_view(store, monkeypatch):
    monkeypatch.setenv("COUNTERCHECK_API_KEY", "k")
    settings = Settings(mode=Mode.frozen, assessment=AssessmentSettings(updater="evidence_accumulator"))
    client = TestClient(create_app(Deps(store=store, index=MemoryIndex(), settings=settings,
                                        llm_factory=FakeLLM)))
    document = client.post("/documents", json={"content": REPORT.decode()}, headers=HEADERS).json()
    job = client.post("/analyses", json={"document_id": document["id"]}, headers=HEADERS).json()
    [finding] = client.get(f"/analyses/{job['id']}/findings", headers=HEADERS).json()
    claim = finding["claim_id"]
    assert finding["probability"] is None
    [update] = client.get(f"/claims/{claim}/updates", headers=HEADERS).json()
    assert not {"belief", "new_score", "previous_score"} & set(update)
    assert client.get(f"/claims/{claim}/research", headers=HEADERS).status_code == 404
    monkeypatch.setenv("COUNTERCHECK_RESEARCH_VIEW", "1")
    research = client.get(f"/claims/{claim}/research", headers=HEADERS).json()
    assert research["target"]["id"] == "material-overstatement-v1"
    assert research["belief"]["calibration_status"] == "uncalibrated"
    assert research["updates"][0]["new_score"] == research["belief"]["raw_probability"]
    assert "not a probability" in research["notice"].lower()


def test_traces_give_the_web_application_one_record_per_finding_without_scores(store, monkeypatch):
    monkeypatch.setenv("COUNTERCHECK_API_KEY", "k")
    settings = Settings(mode=Mode.frozen, assessment=AssessmentSettings(updater="evidence_accumulator"))
    client = TestClient(create_app(Deps(store=store, index=MemoryIndex(), settings=settings,
                                        llm_factory=FakeLLM)))
    document = client.post("/documents", json={"content": REPORT.decode()}, headers=HEADERS).json()
    job = client.post("/analyses", json={"document_id": document["id"]}, headers=HEADERS).json()
    [record] = client.get("/traces", headers=HEADERS).json()
    assert record["analysis_id"] == job["id"] and record["status"] == "contradicted"
    assert record["document"]["title"] == "Example Manufacturing sustainability update"
    assert record["created_at"] and 0 < record["coverage"] <= 1
    assert len(record["evidence"]) == 3 and record["calculations"] and record["questions"]
    assert client.get(f"/traces/{record['id']}", headers=HEADERS).json()["id"] == record["id"]
    assert client.get("/traces/unknown", headers=HEADERS).status_code == 404
    text = str(record)
    assert "raw_probability" not in text and "log_evidence" not in text and "'belief'" not in text
