"""Replay one saved evidence sequence under each updating strategy and under changed sequences.

Usage: python -m evaluation.replay.run --trace TRACE.json --out RESULT.json
           [--provider scripted|openai] [--strategies NAME ...] [--seed 7] [--permutations 3]
           [--max-calls 60] [--prior 0.5] [--tempering 1.0]

The scripted provider makes no network calls. The openai provider is paid, so --max-calls
bounds the whole run.
"""
from __future__ import annotations

import argparse
import json
import random
from copy import deepcopy
from itertools import takewhile
from pathlib import Path

from backend.belief import strategies
from backend.config import AssessmentSettings
from backend.evidence.provenance import lineage, merge, reconcile, withdraw
from backend.models import (
    EvidenceItem, InvestigationState, Mode, Relationship, RunManifest,
)
from backend.orchestration.worker import current_commit
from backend.providers import prompts
from backend.providers.base import ProviderError
from backend.verification.numeric import claim_relation, execute
from evaluation.budget import Budgeted
from evaluation.replay.scripted import ScriptedLLM
from evaluation.replay.trace import Event, Trace, need

STRATEGIES = ["linguistic", "full_context", "evidence_accumulator"]
IRRELEVANT = "The annual general meeting was held at the registered office."


def replay(trace: Trace, settings: AssessmentSettings, llm, manifest: RunManifest) -> dict:
    """Apply the events in order. After each change the configured strategy runs once."""
    claim = trace.claim
    state = InvestigationState(claim=claim, questions=deepcopy(trace.questions),
                               target=strategies.new_target(claim, trace.cutoff))
    steps = []
    for event in trace.events:
        new_evidence: list[str] = []
        new_calculations: list[str] = []
        changed = event.kind in ("withdraw", "correct", "merge")
        if event.kind in ("withdraw", "correct"):
            withdraw(state, need(event.evidence_id, "evidence_id"),
                     "corrected" if event.kind == "correct" else "withdrawn")
        if event.kind == "merge":
            merge(state, *event.group_ids)
        if event.kind in ("admit", "correct"):
            item = need(event.evidence, "evidence").model_copy(deep=True)
            repeats = {item.span_id: item.repeats_span_id} if item.repeats_span_id else {}
            changed = reconcile(state, [item], repeats) or changed
            new_evidence = [item.id]
        if event.kind == "calculate":
            saved = need(event.calculation, "calculation")
            spans = [i.source_span_id for i in saved.inputs]
            result = execute(saved.id, claim.id, saved.inputs, saved.steps, saved.note,
                             lineage(state, spans))
            if result.outputs != saved.outputs:
                raise ValueError(f"{saved.id} does not reproduce its saved outputs")
            expected = None if saved.claim_expected is None else str(saved.claim_expected)
            result.claim_output, result.round = saved.claim_output, saved.round
            result.claim_expected, result.claim_relation = claim_relation(
                result.outputs, saved.claim_output, expected, claim.text)
            state.calculations.append(result)
            new_calculations = [result.id]
        record = None
        if changed or new_calculations:
            try:
                record = strategies.step(state, new_evidence, new_calculations, llm, settings,
                                         manifest, prompts.VERSION)
            except ProviderError as exc:
                manifest.errors.append(str(exc))
        steps.append({"event": event.kind, "id": (new_evidence + new_calculations + [event.evidence_id]
                                                  + event.group_ids)[0],
                      "updated": record is not None, "status": state.assessment.status,
                      "score": state.belief.raw_probability if state.belief else None})
    return {"steps": steps, "final_status": state.assessment.status,
            "final_score": steps[-1]["score"] if steps else None,
            "updates": state.version, "active_groups": sum(g.active for g in state.groups),
            "calls": len(manifest.calls),
            "input_tokens": sum(c.input_tokens for c in manifest.calls),
            "output_tokens": sum(c.output_tokens for c in manifest.calls),
            "latency_ms": sum(c.latency_ms or 0 for c in manifest.calls),
            "errors": manifest.errors, "rejections": manifest.rejections}


def _permuted(trace: Trace, rng: random.Random) -> Trace:
    """Shuffle the admissions before the first withdrawal, correction, or merge.

    A calculation is placed as soon as every passage it reads has been admitted.
    """
    head = list(takewhile(lambda e: e.kind in ("admit", "calculate"), trace.events))
    admits = [e for e in head if e.kind == "admit"]
    waiting = [e for e in head if e.kind == "calculate"]
    rng.shuffle(admits)
    spans_of = {id(e): need(e.evidence, "evidence").span_id for e in admits}
    evidence_spans = set(spans_of.values())
    ordered: list[Event] = []
    present: set[str] = set()
    for event in admits:
        ordered.append(event)
        present.add(spans_of[id(event)])
        ready = [c for c in waiting
                 if {i.source_span_id for i in need(c.calculation, "calculation").inputs}
                 & evidence_spans <= present]
        ordered += ready
        waiting = [c for c in waiting if c not in ready]
    return trace.model_copy(update={"events": ordered + waiting + trace.events[len(head):]})


def variants(trace: Trace, seed: int, permutations: int) -> dict[str, Trace]:
    rng = random.Random(seed)
    out = {"base": trace}
    for k in range(permutations):
        out[f"permutation_{k}"] = _permuted(trace, rng)
    removed = {e.evidence_id for e in trace.events if e.evidence_id}
    admitted = [need(e.evidence, "evidence") for e in trace.events if e.kind == "admit"]
    active = [e for e in admitted if e.id not in removed]
    if not active:
        return out
    pick = rng.choice(active)

    def extended(event: Event) -> Trace:
        return trace.model_copy(update={"events": trace.events + [event]})

    out["duplicate_source"] = extended(Event(kind="admit", evidence=pick.model_copy(
        update={"id": pick.id + "-dup", "span_id": pick.span_id + "-dup"})))
    out["duplicate_event"] = extended(Event(kind="admit", evidence=pick))
    out["irrelevant_addition"] = extended(Event(kind="admit", evidence=EvidenceItem(
        id=f"{trace.claim.id}-irrelevant", claim_id=trace.claim.id, span_id="irrelevant",
        document_id="irrelevant", quote=IRRELEVANT, relationship=Relationship.context,
        target="claim")))
    out["withdrawal"] = extended(Event(kind="withdraw", evidence_id=pick.id))
    # The correction keeps the passage and removes its bearing on the claim.
    out["correction"] = extended(Event(kind="correct", evidence_id=pick.id, evidence=pick.model_copy(
        update={"id": pick.id + "-corrected", "relationship": Relationship.context,
                "limitations": pick.limitations + ["the source corrected this passage"]})))
    return out


def compare(runs: dict[str, dict]) -> dict:
    """Differences from the base run. A score difference is None when either score is missing."""
    base = runs["base"]

    def score_change(name: str) -> float | None:
        a, b = base["final_score"], runs[name]["final_score"]
        return None if a is None or b is None else abs(a - b)

    orders = [n for n in runs if n.startswith("permutation_")]
    ranges = [c for c in map(score_change, orders) if c is not None]
    summary: dict = {"order_changes_status": any(runs[n]["final_status"] != base["final_status"]
                                           for n in orders),
               "order_score_range": max(ranges) if ranges else None}
    for name in runs:
        if name != "base" and name not in orders:
            summary[name] = {"status_changed": runs[name]["final_status"] != base["final_status"],
                             "score_change": score_change(name),
                             "extra_updates": runs[name]["updates"] - base["updates"]}
    return summary


def run_all(trace: Trace, names: list[str], provider: str, seed: int, permutations: int,
            max_calls: int, prior: float, tempering: float) -> dict:
    remaining = max_calls
    results = {}
    for name in names:
        settings = AssessmentSettings.model_validate(
            {"updater": name, "prior": prior, "tempering": tempering})
        runs = {}
        for variant, changed in variants(trace, seed, permutations).items():
            manifest = RunManifest(analysis_id=f"replay-{trace.id}", mode=Mode.replay,
                                   config_hash="", updater=name)
            if provider == "openai":
                from backend.providers.openai_client import OpenAILLM
                llm = Budgeted(OpenAILLM(manifest), remaining)
                runs[variant] = replay(changed, settings, llm, manifest)
                remaining -= llm.calls
            else:
                runs[variant] = replay(changed, settings, ScriptedLLM(trace.scripted_scores),
                                       manifest)
        results[name] = {"runs": runs, "comparison": compare(runs)}
    return {"trace": trace.id, "source": trace.source,
            "is_synthetic_example": trace.is_synthetic_example, "provider": provider,
            "seed": seed, "permutations": permutations, "commit": current_commit(),
            "prompts": prompts.VERSION, "scorer": strategies.SCORER_VERSION, "prior": prior,
            "tempering": tempering, "max_paid_calls": max_calls,
            "paid_calls_used": max_calls - remaining,
            "strategies": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--trace", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--provider", choices=["scripted", "openai"], default="scripted")
    parser.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=STRATEGIES)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--permutations", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=60)
    parser.add_argument("--prior", type=float, default=0.5)
    parser.add_argument("--tempering", type=float, default=1.0)
    args = parser.parse_args()
    trace = Trace.model_validate_json(Path(args.trace).read_text())
    result = run_all(trace, args.strategies, args.provider, args.seed, args.permutations,
                     args.max_calls, args.prior, args.tempering)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, default=str))
    for name, outcome in result["strategies"].items():
        print(name, outcome["runs"]["base"]["final_status"], outcome["runs"]["base"]["final_score"],
              json.dumps(outcome["comparison"], default=str))


if __name__ == "__main__":
    main()
