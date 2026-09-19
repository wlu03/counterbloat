from decimal import Decimal

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.config import Settings
from backend.ingestion.snapshot import admit
from backend.models import Calculation, EvidenceStatus, Finding, InvestigationState, Mode
from backend.orchestration.worker import Deps, run_analysis
from backend.retrieval.memory import MemoryIndex
from tests.fakes import ARTICLE, REPORT, REWRITE, FakeLLM


def _deps(store):
    return Deps(store=store, index=MemoryIndex(), settings=Settings(mode=Mode.frozen),
                llm_factory=FakeLLM)


def _run(deps, contents):
    document_id = None
    for content in contents:
        snapshot, spans = admit(deps.store, content, "text/html")
        deps.index.index(snapshot, spans)
        document_id = document_id or snapshot.id
    job = {"id": "an-1", "document_id": document_id, "mode": "live", "status": "queued"}
    deps.store.put("analyses", "an-1", job, document_id=document_id)
    run_analysis("an-1", deps)
    return deps.store.find("findings", Finding, analysis_id="an-1")


def test_total_emissions_claim_is_contradicted_by_the_reported_figures(store):
    deps = _deps(store)
    [finding] = _run(deps, [REPORT])
    assert finding.evidence_status == EvidenceStatus.contradicted
    assert finding.mechanisms == ["scope", "magnitude"]
    assert finding.supported_rewrite == REWRITE
    assert finding.probability is None and finding.review_status == "checks_passed"
    [calc] = store.find("calculations", Calculation, claim_id=finding.claim_id)
    assert calc.outputs["e24"] == Decimal(10000) and calc.outputs["e25"] == Decimal(12000)
    assert calc.outputs["total_change"] == Decimal(20) and calc.lineage
    [state] = store.find("states", InvestigationState, analysis_id="an-1")
    # The per-unit row is on another basis, so it qualifies the claim instead of contradicting it.
    assert state.evidence[0].relationship == "qualifies" and not state.evidence[0].comparable
    assert state.stop_reason == "no_new_evidence" and len(state.calculations) == 1
    assert [q.status for q in state.questions] == ["answered", "answered", "answered", "open"]
    assert store.get("analyses", "an-1")["status"] == "complete"


def test_articles_repeating_the_report_add_no_evidence_group(store):
    alone = _run(_deps(store), [REPORT])[0]
    groups_alone = len(store.find("states", InvestigationState, analysis_id="an-1")[0].groups)
    repeated = _run(_deps(store), [REPORT, ARTICLE])[0]
    state = store.find("states", InvestigationState, analysis_id="an-1")[0]
    assert len(state.groups) == groups_alone
    assert any(e.origin == "third_party_repetition" for e in state.evidence)
    assert repeated.evidence_status == alone.evidence_status


def test_api_runs_an_analysis_and_requires_the_key(store, monkeypatch):
    monkeypatch.setenv("COUNTERCHECK_API_KEY", "k")
    client = TestClient(create_app(_deps(store)))
    assert client.post("/documents", json={"content": "x"}).status_code == 401
    headers = {"X-API-Key": "k", "Idempotency-Key": "once"}
    document = client.post("/documents", json={"content": REPORT.decode()}, headers=headers).json()
    job = client.post("/analyses", json={"document_id": document["id"]}, headers=headers).json()
    again = client.post("/analyses", json={"document_id": document["id"]}, headers=headers).json()
    assert again["id"] == job["id"]
    assert client.get(f"/analyses/{job['id']}", headers=headers).json()["status"] == "complete"
    [finding] = client.get(f"/analyses/{job['id']}/findings", headers=headers).json()
    assert finding["evidence_status"] == "contradicted" and finding["probability"] is None
    claim = client.get(f"/claims/{finding['claim_id']}", headers=headers).json()
    evidence_id = claim["evidence"][0]["id"]
    source = client.get(f"/evidence/{evidence_id}", headers=headers).json()
    assert source["evidence"]["quote"] in source["span"]["text"]
    assert len(client.get(f"/claims/{finding['claim_id']}/updates", headers=headers).json()) == 1
    reviewed = client.post(f"/findings/{finding['finding_id']}/review", headers=headers,
                           json={"reviewer": "analyst", "decision": "accept"}).json()
    assert reviewed["review_status"] == "human_reviewed"
    export = client.get(f"/analyses/{job['id']}/export", headers=headers).json()
    assert "Supported wording" in export["markdown"] and export["manifest"]["mode"] == "frozen"
    reader = client.get(f"/documents/{document['id']}", headers=headers).json()
    assert reader["text"][claim["claim"]["start"]:claim["claim"]["end"]] == claim["claim"]["text"]
