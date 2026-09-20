"""Dataset preparation, label isolation, the baseline and pipeline runners, the budget, and scoring."""
import json
import stat

import pytest

from backend.config import AssessmentSettings, Settings
from backend.models import AssertionType, Claim, Mode
from datasets.prepare import prepare
from evaluation.experiments.run import detect, run_rows, score, verify
from evaluation.experiments.tasks import VERIFICATION
from tests.fakes import REPORT, FakeLLM

CLAIM = "We reduced our total operational emissions by 40% in 2025 compared with 2024."
TASK = VERIFICATION["averitec"]


def _rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def _prepared(tmp_path):
    source = tmp_path / "averitec.json"
    source.write_text(json.dumps([
        {"claim": CLAIM, "claim_date": "1-1-2026", "speaker": "Example Manufacturing",
         "label": "Refuted", "justification": "Totals rose.", "questions": [],
         "fact_checking_article": "https://factcheck.example/a"}]))
    manifest = prepare("averitec", source, "rev-1", "dev", tmp_path)
    return manifest, tmp_path / "prepared/averitec/dev.visible.jsonl", tmp_path / "gold/averitec/dev.jsonl"


def test_preparation_keeps_labels_out_of_the_runtime_file(tmp_path):
    manifest, visible, gold = _prepared(tmp_path)
    text = visible.read_text()
    assert "Refuted" not in text and "factcheck.example" not in text and "Totals rose" not in text
    assert stat.S_IMODE(gold.stat().st_mode) == 0o600
    record = json.loads(manifest.read_text())
    assert record["rows"] == 1 and record["revision"] == "rev-1" and record["license"] == "CC BY-NC 4.0"
    assert "label" in record["field_mapping"]["evaluation_only"]
    assert "label" not in record["field_mapping"]["model_visible"]
    assert manifest.name == "dev.manifest.json"  # a second split does not overwrite this one


def _settings(updater):
    return Settings(mode=Mode.frozen, assessment=AssessmentSettings(updater=updater))


def test_the_pipeline_runs_without_the_gold_file_and_is_scored_afterwards(tmp_path, monkeypatch):
    monkeypatch.setenv("OBJECT_STORE_DIR", str(tmp_path / "objects"))
    _, visible, gold = _prepared(tmp_path)
    labels = _rows(gold)
    gold.unlink()  # the runs below cannot read labels, because the file is gone
    sources = {"averitec-0": [{"example_id": "averitec-0", "content": REPORT.decode(),
                               "media_type": "text/html"}]}
    settings = _settings("evidence_accumulator")

    def system(name):
        return list(run_rows(_rows(visible), lambda row, factory: verify(
            row, factory, sources, TASK, name, settings), FakeLLM, max_calls=50))

    [baseline], [pipeline] = system("A1"), system("A2")
    assert baseline["status"] == "insufficient" and baseline["score"] is None
    assert baseline["embedding_search"] is False and pipeline["target"] == "averitec-refuted"
    assert pipeline["status"] == "contradicted" and 0.5 < pipeline["score"] < 1
    assert pipeline["embedding_search"] is False  # the run states that no vector search took place

    result = score([pipeline], labels, TASK)
    assert result["status_agreement"] == 1.0 and result["with_score"] == 1
    assert result["brier"] == pytest.approx((pipeline["score"] - 1) ** 2)
    assert result["cost"] == "unknown"  # no price list was given
    unscored = score([baseline], labels, TASK)
    assert unscored["status_agreement"] == 0.0
    assert unscored["brier"] == "unavailable" and unscored["nll"] == "unavailable"


def test_the_internal_score_is_for_the_dataset_target_in_a_dataset_run():
    claim = Claim(id="c", document_id="d", span_id="s", text=CLAIM, start=0, end=len(CLAIM),
                  assertion_type=AssertionType.numerical_comparison)
    target = TASK.target(claim, None)
    assert target.id == "averitec-refuted" and "Refuted" in target.hypothesis


def test_examples_past_the_call_budget_are_not_scored():
    rows = [{"id": i, "text": CLAIM} for i in range(3)]
    predictions = list(run_rows(rows, detect, FakeLLM, max_calls=2))
    # The second example uses the last allowed call and no call of it was refused, so it counts.
    assert [p["status"] for p in predictions] == ["ran", "ran", "not_run"]
    gold = [{"id": 0, "label": 1}, {"id": 1, "label": None}, {"id": 2, "label": 1}]
    result = score(predictions, gold, None)
    assert result["examples"] == 3 and result["scored"] == 1
    assert result["gold_rows_without_a_usable_label"] == 1
    assert result["precision"] == 1.0 and result["recall"] == 1.0


def test_cost_is_a_number_only_when_every_model_has_a_price():
    prediction = {"id": 1, "status": "ran", "predicted": True, "calls": {}, "failed_calls": 0,
                  "latency_ms": 0, "skipped_by_router": 0, "compression_fallbacks": 0,
                  "tokens_by_model": {"m": [100, 50, 10]}}
    gold = [{"id": 1, "label": 1}]
    assert score([prediction], gold, None, {"m": [0.01, 0.001, 0.1]})["cost"] == pytest.approx(2.05)
    assert score([prediction], gold, None, {"other": [1, 1, 1]})["cost"] == "unknown"
    routed = {**prediction, "calls": {"openai:extract": 1, "jev:route": 1}}
    assert score([routed], gold, None, {"m": [0.01, 0.001, 0.1]})["cost"] == "unknown"


def test_a_provider_failure_in_the_pipeline_is_not_scored_as_a_prediction(tmp_path, monkeypatch):
    from backend.providers.base import ProviderError

    class Broken(FakeLLM):
        def analyze_evidence(self, claim, questions, context):
            raise ProviderError("openai analyze failed: 500")

    monkeypatch.setenv("OBJECT_STORE_DIR", str(tmp_path / "objects"))
    sources = {"x": [{"example_id": "x", "content": REPORT.decode(), "media_type": "text/html"}]}
    [prediction] = run_rows([{"id": "x", "claim": CLAIM}], lambda row, factory: verify(
        row, factory, sources, TASK, "A2", _settings("linguistic")), Broken, max_calls=50)
    assert prediction["status"] == "not_run" and prediction["errors"] == 1
    assert score([prediction], [{"id": "x", "label": "Refuted"}], TASK)["scored"] == 0


def test_a_saturated_score_does_not_break_the_log_likelihood():
    prediction = {"id": 1, "status": "contradicted", "score": 1.0, "target": "averitec-refuted",
                  "calls": {}, "failed_calls": 0, "latency_ms": 0, "skipped_by_router": 0,
                  "compression_fallbacks": 0, "tokens_by_model": {}}
    result = score([prediction], [{"id": 1, "label": "Refuted"}], TASK)
    assert result["nll"] == pytest.approx(0, abs=1e-9) and result["target"] == ["averitec-refuted"]


def test_climate_fever_and_quantemp_are_scored_on_their_own_label_fields():
    def prediction(status):
        return {"id": "x", "status": status, "score": None, "target": None, "calls": {}, "failed_calls": 0,
                "latency_ms": 0, "skipped_by_router": 0, "compression_fallbacks": 0, "tokens_by_model": {}}

    climate = VERIFICATION["climate_fever"]
    assert score([prediction("mixed")], [{"id": "x", "claim_label": "DISPUTED"}], climate)["status_agreement"] == 1.0
    assert score([prediction("supported")], [{"id": "x", "claim_label": "REFUTES"}], climate)["status_agreement"] == 0.0
    quantemp = VERIFICATION["quantemp"]
    assert score([prediction("contradicted")], [{"id": "x", "label": "False"}], quantemp)["status_agreement"] == 1.0
    # QuanTemp has no class for too little evidence, so abstaining never agrees with it.
    assert score([prediction("insufficient")], [{"id": "x", "label": "True"}], quantemp)["status_agreement"] == 0.0
    assert quantemp.target(Claim(id="c", document_id="d", span_id="s", text="t", start=0, end=1,
                                 assertion_type=AssertionType.numerical_comparison), None).id == "quantemp-false"


def test_a_seed_samples_rows_instead_of_taking_the_first_ones(tmp_path):
    from evaluation.experiments.run import _read

    source = tmp_path / "rows.jsonl"
    source.write_text("\n".join(json.dumps({"id": i}) for i in range(100)))
    assert [r["id"] for r in _read(source, 5)] == [0, 1, 2, 3, 4]
    sampled = [r["id"] for r in _read(source, 5, seed=7)]
    assert sampled != [0, 1, 2, 3, 4] and len(set(sampled)) == 5
    assert sampled == [r["id"] for r in _read(source, 5, seed=7)]      # the same seed, the same rows
    assert len(_read(source, 500, seed=7)) == 100                      # a sample larger than the file
