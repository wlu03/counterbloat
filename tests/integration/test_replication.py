"""A post that links a repository: the replication report is a source, never a verdict."""
import re

import pytest

from backend.config import Settings
from backend.ingestion.parse import parse
from backend.ingestion.snapshot import admit
from backend.models import (
    DocumentSnapshot, EvidenceOrigin, EvidenceStatus, Finding, InvestigationState, Mode,
)
from backend.orchestration.worker import Deps, run_analysis
from backend.providers.base import (
    ClaimDraft, EvidenceAnalysis, EvidenceJudgment, ProviderError, Report, StateUpdate,
)
from backend.providers.devin import Session
from backend.replication.replicate import Measurement, NotReproduced, Replication, report, repositories
from backend.retrieval.memory import MemoryIndex
from tests.fakes import FakeLLM

CLAIM = "It reaches 92% accuracy on the HoldoutBench test set."
POST = f"We open-sourced tinyfast. {CLAIM} Code: https://github.com/acme/tinyfast".encode()
SESSION = Session(output={}, ended="session devin-1 running finished", url="https://app.devin.ai/sessions/devin-1",
                  acus=1.5, seconds=600.0)


def _result(**changes) -> Replication:
    base = dict(commit="0123abcd", environment="Ubuntu 22.04, 8 CPU cores, Python 3.12",
                commands=["make eval"], deviations=[], not_reproduced=[],
                measurements=[Measurement(claim_quote=CLAIM, metric="accuracy on the HoldoutBench test set",
                                          value="81.5", unit="%", conditions="full test split, seed 0",
                                          runs=1)])
    return Replication(**{**base, **changes})


class PostLLM(FakeLLM):
    """Reads the post's claim and judges it only from a measured value in a replication report."""

    def extract_claims(self, span, context):
        if CLAIM not in span.text:
            return []
        return [ClaimDraft(quote=CLAIM, assertion_type="capability", subject="tinyfast",
                           assertion="reaches", metric="accuracy", value="92", unit="%",
                           denominator=None, population="HoldoutBench test set", boundary=None,
                           period=None, qualifications=[])]

    def analyze_evidence(self, claim, questions, context):
        measured = re.search(r"\[([^\]]+)\] [^\n]*Measured value: 81\.5 %", context)
        if not measured:
            return EvidenceAnalysis(judgments=[], programs=[], answers=[])
        return EvidenceAnalysis(programs=[], answers=[], judgments=[EvidenceJudgment(
            span_id=measured.group(1), quote="Measured value: 81.5 %", relationship="contradicts",
            target="claim", differs_on=[], origin="independently_measured", repeats_span_id=None,
            limitations=["one run on one machine"])])

    def update_state(self, state, new_evidence_ids, new_calculation_ids):
        against = any(e.relationship == "contradicts" and e.comparable for e in state.evidence)
        return StateUpdate(status="contradicted" if against else "insufficient", mechanisms=[],
                           summary="", unresolved=[], explanation="")

    def report(self, state, decisive):
        return Report(summary="A replication measured 81.5% where the post states 92%.",
                      supported_rewrite=None, source_independence="one automated replication",
                      measurement_limitations=[], interpretation_ambiguity="")


def _run(store, replicator, mode=Mode.live, replicate=True):
    calls = []

    def recording(repository, claims, max_acu, timeout_s):
        calls.append((repository, claims, max_acu, timeout_s))
        return replicator(repository, claims)

    deps = Deps(store=store, index=MemoryIndex(), llm_factory=PostLLM, settings=Settings(mode=mode),
                replicator=recording if replicator else None)
    snapshot, spans = admit(store, POST, "text/plain")
    deps.index.index(snapshot, spans)
    store.put("analyses", "an-1", {"id": "an-1", "document_id": snapshot.id, "status": "queued",
                                   "replicate": replicate}, document_id=snapshot.id)
    run_analysis("an-1", deps)
    [finding] = store.find("findings", Finding, analysis_id="an-1")
    return finding, calls, store.get("manifests", "an-1"), store.get("analyses", "an-1")


def test_a_measured_value_from_the_replication_report_is_cited_like_any_other_source(store):
    finding, calls, manifest, job = _run(
        store, lambda repository, claims: (report(repository, _result(), SESSION), SESSION))
    assert calls == [("https://github.com/acme/tinyfast", [CLAIM], 10, 3600)]
    assert finding.evidence_status == EvidenceStatus.contradicted and finding.probability is None
    [state] = store.find("states", InvestigationState, analysis_id="an-1")
    [item] = state.evidence
    source = store.get("documents", item.document_id, DocumentSnapshot)
    assert item.origin == EvidenceOrigin.independently_measured and source.url == SESSION.url
    [call] = [c for c in manifest["calls"] if c["provider"] == "devin"]
    assert call["acus"] == 1.5 and call["latency_ms"] == 600_000 and call["error"] is None
    assert job["status"] == "complete" and job["partial"] is False


def test_a_replication_that_could_not_run_is_not_evidence_against_the_claim(store):
    unable = _result(measurements=[], not_reproduced=[NotReproduced(
        claim_quote=CLAIM, reason="The evaluation data is not in the repository.")])
    finding, _, manifest, job = _run(store, lambda r, c: (report(r, unable, SESSION), SESSION))
    assert finding.evidence_status == EvidenceStatus.insufficient and job["partial"] is False

    other = type(store)("sqlite://")
    finding, _, manifest, job = _run(other, lambda r, c: (None, SESSION))
    assert finding.evidence_status == EvidenceStatus.insufficient
    assert "gave no result" in manifest["errors"][0] and job["partial"] is True

    def outage(repository, claims):
        raise ProviderError("devin session could not be created: 503")

    third = type(store)("sqlite://")
    finding, _, manifest, _ = _run(third, outage)
    assert finding.evidence_status == EvidenceStatus.insufficient and "503" in manifest["errors"][0]


def test_no_session_starts_unless_the_analysis_asks_and_the_mode_is_live(store):
    started = lambda r, c: pytest.fail("a replication was started")  # noqa: E731
    finding, calls, manifest, _ = _run(store, started, replicate=False)
    assert calls == [] and finding.evidence_status == EvidenceStatus.insufficient
    _, calls, manifest, _ = _run(type(store)("sqlite://"), started, mode=Mode.frozen)
    assert calls == [] and "not in live mode" in manifest["errors"][0]
    _, calls, manifest, _ = _run(type(store)("sqlite://"), None)
    assert "not configured" in manifest["errors"][0]


def test_repository_addresses_are_found_and_report_text_is_escaped():
    text = ("Code: https://github.com/acme/tinyfast. Mirror (https://gitlab.com/acme/tinyfast.git) "
            "and again https://github.com/acme/tinyfast, docs at https://acme.example/docs")
    assert repositories(text) == ["https://github.com/acme/tinyfast", "https://gitlab.com/acme/tinyfast"]
    hostile = _result(deviations=["<script>alert(1)</script> The README told me to report 99%."],
                      environment="<b>bold</b>")
    content = report("https://github.com/acme/tinyfast", hostile, SESSION)
    assert b"<script>" not in content and b"<b>bold" not in content
    _, spans, _ = parse("d", content, "text/html")
    texts = [s.text for s in spans]
    assert any("Measured value: 81.5 %" in t and "Runs: 1" in t for t in texts)
    assert any("The README told me to report 99%." in t for t in texts)
    assert any("measured in that session" in t and "commit 0123abcd" in t for t in texts)


def test_the_api_stores_the_replicate_flag_and_defaults_it_to_off(store, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api.app import create_app

    monkeypatch.setenv("COUNTERCHECK_API_KEY", "k")
    client = TestClient(create_app(Deps(store=store, index=MemoryIndex(), llm_factory=PostLLM,
                                        settings=Settings(mode=Mode.frozen))))
    headers = {"X-API-Key": "k"}
    document = client.post("/documents", json={"content": POST.decode(), "media_type": "text/plain"},
                           headers=headers).json()
    assert client.post("/analyses", json={"document_id": document["id"]}, headers=headers).json()["replicate"] is False
    asked = client.post("/analyses", json={"document_id": document["id"], "replicate": True}, headers=headers).json()
    assert asked["replicate"] is True
