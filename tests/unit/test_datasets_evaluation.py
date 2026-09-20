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
from datasets import fetch as dataset_fetch
from datasets.adapters import climate_fever, finqa, greenclaims, quantemp
from datasets.adapters.base import export
from datasets.manifests.manifest import write_manifest
from evaluation.ablations.configs import settings_for
from evaluation.components.metrics import (
    brier, precision_recall, run_cost, selective_error, token_reduction,
)
from evaluation.robustness.evidence_change import (
    order_does_not_matter, repeating_adds_nothing, withdrawal_recomputes,
)


class _Response:
    """Stands in for urlopen's context manager."""
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def read(self): return self.body


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


def test_quantemp_keeps_the_fact_check_out_of_the_model_input(tmp_path):
    source = tmp_path / "q.json"
    source.write_text(json.dumps([{"claim": "Costs rose 40% in a year.", "label": "False",
                                   "label_original": "pants-fire", "taxonomy_label": "statistical  ",
                                   "doc": "The fact-checker rated this false.",
                                   "url": "https://www.politifact.com/factchecks/x/",
                                   "country_of_origin": "usa", "lang": "en"}]))
    [example] = quantemp.load(source)
    assert example.model_visible == {"claim": "Costs rose 40% in a year.",
                                     "country_of_origin": "usa", "lang": "en"}
    assert example.evaluation_only["label"] == "False"
    assert example.evaluation_only["taxonomy_label"] == "statistical"


def test_quantemp_without_a_verdict_is_refused(tmp_path):
    source = tmp_path / "q.json"
    source.write_text(json.dumps([{"claim": "Costs rose.", "taxonomy_label": "statistical"}]))
    with pytest.raises(ValueError, match="missing gold label"):
        list(quantemp.load(source))


def test_climate_fever_shows_evidence_sentences_but_not_their_labels(tmp_path):
    source = tmp_path / "c.jsonl"
    source.write_text(json.dumps(
        {"claim_id": 7, "claim": "Sea level is rising.", "claim_label": "SUPPORTS",
         "evidences": [{"evidence_id": "Sea level:1", "article": "Sea level",
                        "evidence": "Tide gauges show a rise.", "evidence_label": "SUPPORTS",
                        "votes": ["SUPPORTS"], "entropy": 0.0}]}) + "\n")
    [example] = climate_fever.load(source)
    assert example.id == "climate_fever-7"
    assert example.model_visible["evidence"] == [
        {"evidence_id": "Sea level:1", "article": "Sea level", "evidence": "Tide gauges show a rise."}]
    assert example.evaluation_only["claim_label"] == "SUPPORTS"
    assert example.evaluation_only["evidence_labels"][0]["evidence_label"] == "SUPPORTS"


def test_climate_fever_maps_a_parquet_style_integer_label(tmp_path):
    source = tmp_path / "c.jsonl"
    source.write_text(json.dumps({"claim_id": 0, "claim": "x", "claim_label": 3,
                                  "evidences": []}) + "\n")
    [example] = climate_fever.load(source)
    assert example.evaluation_only["claim_label"] == "DISPUTED"


def test_a_changed_upstream_file_is_refused(tmp_path, monkeypatch):
    source = {"page": "https://example.invalid", "license": "unverified",
              "files": {"x.json": ("https://example.invalid/x.json", "0" * 64)}}
    monkeypatch.setitem(dataset_fetch.SOURCES, "probe", source)
    monkeypatch.setattr(dataset_fetch.urllib.request, "urlopen",
                        lambda *a, **k: _Response(b'{"claim": "x"}'))
    with pytest.raises(ValueError, match="SHA256"):
        dataset_fetch.fetch("probe", tmp_path)


def test_every_fetchable_dataset_is_an_adapter_or_a_corpus():
    from datasets.prepare import ADAPTERS
    assert set(dataset_fetch.SOURCES) - dataset_fetch.CORPORA <= set(ADAPTERS)


def test_climate_fever_evidence_sentences_become_searchable_documents_without_labels(tmp_path):
    source = tmp_path / "cf.jsonl"
    source.write_text(json.dumps({"claim_id": 7, "claim": "Sea level is rising.", "claim_label": "SUPPORTS",
                                  "evidences": [{"evidence_id": "Sea level rise:3", "article": "Sea level rise",
                                                 "evidence": "Sea level rose 20 cm.", "evidence_label": "SUPPORTS",
                                                 "votes": ["SUPPORTS"], "entropy": 0.0}]}) + "\n")
    [example] = climate_fever.load(source)
    assert example.searchable == [{"content": "Sea level rose 20 cm.", "media_type": "text/plain",
                                   "url": "https://en.wikipedia.org/wiki/Sea_level_rise"}]
    assert "SUPPORTS" not in json.dumps(example.searchable)


def test_quantemp_snippets_that_name_a_fact_checker_or_a_rating_are_not_searchable(tmp_path):
    import zipfile

    claims = tmp_path / "test_claims_quantemp.json"
    claims.write_text(json.dumps([{"claim": "Unemployment fell to 3.5%. ", "label": "True"},
                                  {"claim": "A claim with no retrieved snippets.", "label": "False"}]))
    snippets = (["The rate fell to 3.5% in September, the bureau said.", "PolitiFact rated this claim Mostly True.",
                 "Fact check: did unemployment fall?", "The claim was rated false by reviewers.", "  "]
                + [f"Background snippet number {n}." for n in range(40)])
    with zipfile.ZipFile(tmp_path / quantemp.EVIDENCE, "w") as archive:
        archive.writestr(quantemp.EVIDENCE.removesuffix(".zip"),
                         json.dumps([{"claim": "Unemployment fell to 3.5%.", "docs": snippets}]))
    first, second = quantemp.load(claims)
    texts = [d["content"] for d in first.searchable]
    assert texts[0].startswith("The rate fell") and len(texts) == quantemp.SNIPPETS_PER_CLAIM
    assert not any(quantemp.LEAK.search(t) for t in texts) and second.searchable == []
    assert "label" not in first.model_visible


def test_prepare_writes_the_searchable_file_and_counts_it(tmp_path):
    from datasets.prepare import prepare

    source = tmp_path / "cf.jsonl"
    source.write_text(json.dumps({"claim_id": 1, "claim": "c", "claim_label": "REFUTES", "evidences": [
        {"evidence_id": "A:1", "article": "A", "evidence": "One sentence.", "evidence_label": "REFUTES"}]}) + "\n")
    manifest = json.loads(prepare("climate_fever", source, "rev", "all", tmp_path).read_text())
    rows = (tmp_path / "prepared/climate_fever/all.searchable.jsonl").read_text().splitlines()
    assert json.loads(rows[0]) == {"example_id": "climate_fever-1", "content": "One sentence.",
                                   "media_type": "text/plain", "url": "https://en.wikipedia.org/wiki/A"}
    assert manifest["field_mapping"]["searchable_documents"] == 1
    assert "REFUTES" not in (tmp_path / "prepared/climate_fever/all.visible.jsonl").read_text()
