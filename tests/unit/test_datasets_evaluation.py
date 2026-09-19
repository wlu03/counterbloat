import json
import stat

import pytest

from backend.belief.state import apply_update
from backend.config import Settings
from backend.evidence.provenance import reconcile
from backend.models import (
    AssertionType, Claim, EvidenceItem, EvidenceStatus, InvestigationState, ProviderCall,
    Relationship, RunManifest,
)
from backend.providers.base import StateUpdate
from datasets.adapters import finqa, greenclaims
from datasets.adapters.base import export
from datasets.manifests.manifest import write_manifest
from evaluation.ablations.configs import settings_for
from evaluation.components.metrics import (
    brier, precision_recall, run_cost, selective_error, token_reduction,
)
from evaluation.robustness.evidence_change import (
    order_does_not_matter, repeating_adds_nothing, withdrawal_recomputes,
)


def _state():
    claim = Claim(id="c", document_id="d", span_id="s", text="x", start=0, end=1,
                  assertion_type=AssertionType.reported_achievement)
    return InvestigationState(claim=claim)


def _item(i, quote):
    return EvidenceItem(id=f"e{i}", claim_id="c", span_id=f"s{i}", document_id="d", quote=quote,
                        relationship=Relationship.supports, target="claim")


def test_gold_fields_are_written_to_a_separate_owner_only_file(tmp_path):
    source = tmp_path / "finqa.json"
    source.write_text(json.dumps([{"id": "f1", "pre_text": ["a"], "post_text": ["b"],
                                   "table": [["x", "1"]],
                                   "qa": {"question": "q?", "program": "add(1,2)", "exe_ans": 3}}]))
    examples = list(finqa.load(source))
    export(examples, tmp_path / "visible.jsonl", tmp_path / "gold" / "finqa.jsonl")
    visible = (tmp_path / "visible.jsonl").read_text()
    assert "program" not in visible and "exe_ans" not in visible and "q?" in visible
    mode = stat.S_IMODE((tmp_path / "gold" / "finqa.jsonl").stat().st_mode)
    assert mode == 0o600
    manifest = write_manifest("finqa", source, len(examples), "abc123", "MIT", ["train"],
                              {"qa.question": "question"}, tmp_path)
    assert json.loads(manifest.read_text())["rows"] == 1


def test_greenclaims_accusation_is_evaluation_only(tmp_path):
    source = tmp_path / "g.csv"
    source.write_text("Company,Year,Url,Claim,Accusation,Company_description,Type,certificates\n"
                      "Acme,2022,https://a.example,Carbon neutral,Disputed by regulator,,ad,\n")
    [example] = greenclaims.load(source)
    assert example.model_visible["claim"] == "Carbon neutral"
    assert "accusation" not in example.model_visible
    assert example.evaluation_only["accusation"] == "Disputed by regulator"


def test_metrics():
    assert precision_recall([True, True, False], [True, False, True]) == (0.5, 0.5)
    assert brier([0.75, 0.25], [1, 0]) == pytest.approx(0.0625)
    assert selective_error([False, False], [1, 0], [1, 1]) is None
    assert selective_error([True, True], [1, 0], [1, 1]) == 0.5
    assert token_reduction(60, 100) == pytest.approx(0.4)
    manifest = RunManifest(analysis_id="a", mode="frozen", config_hash="h", calls=[
        ProviderCall(provider="openai", purpose="x", model="m", input_tokens=1000,
                     cached_tokens=400, output_tokens=100),
        ProviderCall(provider="ttc", purpose="compress", billing_unit="removed_tokens")])
    assert run_cost(manifest, {"m": (2e-6, 2e-7, 1e-5)}) == pytest.approx(0.00228)


def test_ablation_settings_toggle_only_the_optimizations():
    a5 = settings_for("A5", Settings())
    a2 = settings_for("A2", Settings())
    assert a5.optimization.jev_routing and a5.optimization.protected_compression
    assert not a2.optimization.jev_routing and not a2.optimization.protected_compression


def test_evidence_change_checks():
    state = _state()
    reconcile(state, [_item(1, "Per-unit emissions fell 40%.")], {})
    assert repeating_adds_nothing(state, _item(1, "Per-unit emissions fell 40%."))
    assert order_does_not_matter(_state, [_item(1, "Output doubled."), _item(2, "Method unchanged.")])
    assert withdrawal_recomputes(state, "e1")


def test_a_verdict_without_evidence_becomes_insufficient():
    state = _state()
    update = StateUpdate(status=EvidenceStatus.contradicted, mechanisms=["scope"], summary="s",
                         unresolved=[], explanation="e")
    record = apply_update(state, update, [], [], "v")
    assert state.assessment.status == EvidenceStatus.insufficient
    assert record.new_status == EvidenceStatus.insufficient and state.assessment.mechanisms == []


def test_an_example_without_a_gold_label_is_refused(tmp_path):
    source = tmp_path / "finqa.json"
    source.write_text(json.dumps([{"id": "f1", "pre_text": ["a"], "post_text": ["b"],
                                   "table": [["x", "1"]],
                                   "qa": {"question": "q?", "program": "add(1,2)"}}]))
    with pytest.raises(ValueError, match="missing gold exe_ans"):
        list(finqa.load(source))


def test_a_zero_answer_still_counts_as_a_gold_label(tmp_path):
    source = tmp_path / "finqa.json"
    source.write_text(json.dumps([{"id": "f1", "pre_text": ["a"], "post_text": ["b"],
                                   "table": [["x", "1"]],
                                   "qa": {"question": "q?", "program": "add(1,-1)", "exe_ans": 0}}]))
    [example] = finqa.load(source)
    assert example.evaluation_only["exe_ans"] == 0
