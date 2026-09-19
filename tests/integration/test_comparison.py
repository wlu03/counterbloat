"""The three-arm comparison: shared inputs, label isolation, the Devin client, and the scorer."""
import json

import httpx
import pytest

from backend.config import Settings
from backend.models import Mode
from backend.providers.base import ProviderError
from evaluation.comparison import arms
from evaluation.comparison.run import load_cases, markdown, run
from evaluation.comparison.schema import (
    AuditFinding, AuditNumber, AuditOutput, AuditQuote, Case, CaseDocument, Expected,
)
from evaluation.comparison.score import score
from tests.fakes import REPORT, FakeLLM

CLAIM = "We reduced our total operational emissions by 40% in 2025 compared with 2024."
CASE = Case(id="emissions", category="arithmetic_contradiction",
            documents=[CaseDocument(name="report", role="audited", content=REPORT.decode())],
            expected=Expected(claim_contains="reduced our total operational emissions by 40%",
                              accept_statuses=["contradicted"], key_numbers=["20"],
                              derived_numbers=["10000", "12000", "20"],
                              rationale="SECRET-RATIONALE"))


@pytest.fixture(autouse=True)
def _objects(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_DIR", str(tmp_path / "objects"))


def _finding(**changes):
    base = dict(claim_quote=CLAIM, status="contradicted", evidence=[], computed=[],
                summary="Totals rose 20% from 10,000 to 12,000.", supported_rewrite=None,
                probability=None)
    return AuditFinding(**{**base, **changes})


def test_the_scorer_checks_quotes_numbers_and_probability_against_the_documents():
    prepared = arms.Prepared(CASE)
    good = _finding(evidence=[AuditQuote(document_id=prepared.audited, quote="2024: 10 | 2025: 6")],
                    computed=[AuditNumber(name="change", value="20.0", unit="%")])
    result = score(CASE, prepared.passages, AuditOutput(findings=[good]))
    assert result["status_correct"] and result["quotes_exact"] == result["quotes"] == 1
    assert result["key_numbers_found"] == 1 and result["unverified_numbers"] == []
    assert result["probability_stated"] is False

    bad = _finding(status="supported", probability=0.9,
                   summary="Emissions fell 40%, saving 3,700 tonnes.",
                   evidence=[AuditQuote(document_id=prepared.audited, quote="emissions fell sharply")])
    result = score(CASE, prepared.passages, AuditOutput(findings=[bad]))
    assert not result["status_correct"] and result["quotes_exact"] == 0
    assert result["key_numbers_found"] == 0 and result["unverified_numbers"] == ["3700"]
    assert result["probability_stated"] is True

    missed = score(CASE, prepared.passages, AuditOutput(findings=[_finding(claim_quote="Other.")]))
    assert missed == {"claim_found": False, "status": None, "status_correct": False,
                      "other_findings": 1, "key_numbers": 1, "key_numbers_found": 0}


def test_a_key_number_counts_only_when_it_was_calculated():
    prepared = arms.Prepared(CASE)

    def found(case=CASE, **changes):
        return score(case, prepared.passages, AuditOutput(findings=[_finding(**changes)]))["key_numbers_found"]

    # 40 is written in the claim, so repeating it in the summary is not a calculation.
    restated = CASE.model_copy(update={"expected": CASE.expected.model_copy(update={"key_numbers": ["40"]})})
    assert found(restated, status="insufficient", summary="The report says emissions fell 40%.") == 0
    assert found(restated, computed=[AuditNumber(name="cut", value="40", unit="%")]) == 1
    # A share given as a fraction of 1 is the same result as the percentage.
    assert found(summary="", computed=[AuditNumber(name="change", value="0.2", unit="ratio")]) == 1
    assert found(summary="", computed=[AuditNumber(name="change", value="0.2", unit="t")]) == 0
    # Digits inside a passage id are not figures.
    assert found(summary="See doc-0000000000000020-s20.") == 0


def test_a_claim_quote_that_overlaps_the_expected_text_is_matched():
    prepared = arms.Prepared(CASE)
    partial = "We reduced our total operational emissions by 40% in 2025"  # stops before the end
    result = score(CASE, prepared.passages, AuditOutput(findings=[
        _finding(claim_quote="Example Manufacturing sustainability update", status="supported"),
        _finding(claim_quote=partial)]))
    assert result["claim_found"] and result["status"] == "contradicted" and result["other_findings"] == 1


def test_every_arm_reads_the_same_passages_and_none_is_given_the_expected_answer():
    seen = {}

    class Single(FakeLLM):
        def ask(self, purpose, instructions, payload, schema):
            seen["payload"] = payload
            return AuditOutput(findings=[_finding()])

    prepared = arms.Prepared(CASE)
    output, usage = arms.chatgpt(prepared, Single)
    sent = json.dumps(seen["payload"])
    assert "2024: 10 | 2025: 6" in sent and CLAIM in sent
    assert "SECRET-RATIONALE" not in sent and "accept_statuses" not in sent
    assert output.findings[0].status == "contradicted" and usage["calls"] == 0

    output, _ = arms.pipeline(arms.Prepared(CASE), FakeLLM, Settings(mode=Mode.frozen))
    result = score(CASE, prepared.passages, output)
    assert result["status_correct"] and result["key_numbers_found"] == 1
    assert result["quotes_exact"] == result["quotes"] > 0 and result["probability_stated"] is False


def _devin_client(sessions):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"session_id": "devin-1", "url": "https://app/devin-1",
                                             "status": "new"})
        return httpx.Response(200, json=sessions.pop(0))
    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def test_the_devin_arm_creates_one_session_polls_it_and_reads_the_structured_output(monkeypatch):
    monkeypatch.setenv("DEVIN_API_KEY", "cog_test")
    monkeypatch.setenv("DEVIN_ORG_ID", "org-test")
    answer = AuditOutput(findings=[_finding()]).model_dump(mode="json")
    client, requests = _devin_client([
        {"status": "running"},  # just started: no detail yet, so the client keeps waiting
        {"status": "running", "status_detail": "working"},
        {"status": "running", "status_detail": "finished", "structured_output": answer,
         "acus_consumed": 0.4, "url": "https://app/devin-1"}])
    output, usage = arms.devin(arms.Prepared(CASE), client=client, sleep=lambda s: None)
    assert output.findings[0].status == "contradicted" and usage["acus"] == 0.4
    created = requests[0]
    assert str(created.url) == "https://api.devin.ai/v3/organizations/org-test/sessions"
    assert created.headers["authorization"] == "Bearer cog_test"
    body = json.loads(created.content)
    assert body["structured_output_required"] is True and body["max_acu_limit"] == 5
    assert "$ref" not in json.dumps(body["structured_output_schema"])
    assert "2024: 10 | 2025: 6" in body["prompt"] and "SECRET-RATIONALE" not in body["prompt"]
    assert [r.method for r in requests] == ["POST", "GET", "GET", "GET"]

    client, _ = _devin_client([{"status": "running", "status_detail": "finished",
                                "structured_output": {"findings": [{"status": "true"}]}}])
    with pytest.raises(arms.NoAnswer, match="another format"):
        arms.devin(arms.Prepared(CASE), client=client, sleep=lambda s: None)

    client, _ = _devin_client([{"status": "exit", "status_detail": "usage_limit_exceeded",
                                "acus_consumed": 5}])
    with pytest.raises(arms.NoAnswer, match="without structured output") as failure:
        arms.devin(arms.Prepared(CASE), client=client, sleep=lambda s: None)
    assert failure.value.usage["acus"] == 5  # the spent session is still counted as cost


def test_a_failed_status_request_is_retried_and_a_timed_out_session_is_stopped(monkeypatch):
    monkeypatch.setenv("DEVIN_API_KEY", "cog_test")
    monkeypatch.setenv("DEVIN_ORG_ID", "org-test")
    answer = AuditOutput(findings=[_finding()]).model_dump(mode="json")
    replies = [httpx.Response(502), httpx.Response(200, text="<html>maintenance</html>"),
               httpx.Response(200, json={"status": "running", "status_detail": "finished",
                                         "structured_output": answer})]
    requests = []

    def handler(request):
        requests.append(request.method)
        if request.method == "POST":
            return httpx.Response(200, json={"session_id": "devin-1"})
        return replies.pop(0) if request.method == "GET" else httpx.Response(200, json={})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    output, _ = arms.devin(arms.Prepared(CASE), client=client, sleep=lambda s: None)
    assert output.findings[0].status == "contradicted" and requests == ["POST", "GET", "GET", "GET"]

    replies[:] = [httpx.Response(200, json={"status": "running", "status_detail": "working"})] * 3
    requests.clear()
    with pytest.raises(arms.NoAnswer, match="did not finish"):
        arms.devin(arms.Prepared(CASE), client=client, sleep=lambda s: None, timeout_s=-1)
    assert requests == ["POST", "GET", "DELETE"]


def test_a_run_without_an_answer_is_a_miss_and_stored_outputs_can_be_scored_again(monkeypatch):
    monkeypatch.delenv("DEVIN_API_KEY", raising=False)

    class Crashing(FakeLLM):
        def analyze_evidence(self, claim, questions, context):
            raise RuntimeError("a defect inside the pipeline")

        def ask(self, purpose, instructions, payload, schema):
            return AuditOutput(findings=[_finding()])

    result = run([CASE], ["pipeline", "chatgpt"], 1, Crashing, Settings(mode=Mode.frozen), 500)
    pipeline = result["arms"]["pipeline"]["summary"]
    assert pipeline["cases_run"] == 1 and pipeline["no_answer"] == 1
    assert pipeline["status_correct"] == 0.0 and pipeline["cases_failed"] == 0
    assert "no answer (wrong)" in markdown(result)

    again = run([CASE], [], 1, Crashing, Settings(mode=Mode.frozen), 0, reuse=result)
    assert again["arms"]["chatgpt"]["summary"]["status_correct"] == 1.0
    assert again["arms"]["chatgpt"]["rows"][0]["key_numbers_found"] == 1


def test_a_run_reports_an_arm_without_credentials_as_unavailable(monkeypatch):
    monkeypatch.delenv("DEVIN_API_KEY", raising=False)

    class Single(FakeLLM):
        def ask(self, purpose, instructions, payload, schema):
            return AuditOutput(findings=[_finding(status="supported")])

    result = run([CASE], ["pipeline", "chatgpt", "devin"], 2, Single, Settings(mode=Mode.frozen),
                 max_calls=500)
    assert result["arms"]["pipeline"]["summary"]["status_correct"] == 1.0
    assert result["arms"]["pipeline"]["summary"]["same_status_across_repeats"] == 1.0
    assert result["arms"]["chatgpt"]["summary"]["status_correct"] == 0.0
    assert result["arms"]["devin"]["available"] is False
    table = markdown(result)
    assert "The devin arm did not run" in table and "| emissions |" in table
    assert "contradicted (correct), contradicted (correct)" in table


def test_the_shipped_cases_load_and_quote_their_claim_exactly():
    for case in load_cases():
        [audited] = [d for d in case.documents if d.role == "audited"]
        assert case.expected.claim_contains in audited.content, case.id
        assert case.expected.accept_statuses, case.id
