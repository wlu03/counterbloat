"""Run a system on prepared runtime inputs, then score the predictions in a separate step.

  python -m evaluation.experiments.run detect --visible V.jsonl --out P.jsonl [--jev]
  python -m evaluation.experiments.run verify --dataset averitec --visible V.jsonl --out P.jsonl
      [--searchable S.jsonl] [--system A1|A2|A3|A4|A5] [--updater NAME]
  python -m evaluation.experiments.run score --predictions P.jsonl --gold G.jsonl --out R.json
      [--dataset averitec] [--prices PRICES.json]

detect and verify never open a gold file. They call OpenAI, which is paid, so --max-calls bounds
the run and --limit bounds the number of examples. Examples not reached are reported as not run.
S.jsonl rows: {"example_id", "content", "media_type"?, "url"?, "published_at"?}. PRICES.json maps
a model name to [input, cached input, output] price per token.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from backend.claims.extract import extract
from backend.config import Settings, load_settings
from backend.db import Store
from backend.ingestion.snapshot import admit
from backend.models import (
    AssertionType, Claim, Finding, InvestigationState, Mode, RunManifest, SourceSpan,
)
from backend.orchestration.worker import Deps, current_commit, run_analysis
from backend.providers.base import ProviderError, Router
from backend.retrieval.memory import MemoryIndex
from datasets.adapters.base import read_rows
from evaluation.ablations.baselines import retrieve_then_judge
from evaluation.ablations.configs import ABLATIONS, settings_for
from evaluation.budget import Budgeted
from evaluation.components.metrics import brier, nll, precision_recall
from evaluation.experiments.tasks import VERIFICATION, VerificationTask


def _usage(manifest: RunManifest) -> dict:
    """What a run cost in calls, tokens, and time, with failures and fallbacks counted."""
    tokens: dict[str, list[int]] = {}
    for call in manifest.calls:
        if call.billing_unit == "tokens" and call.model:
            used = tokens.setdefault(call.model, [0, 0, 0])
            used[0] += call.input_tokens - call.cached_tokens
            used[1] += call.cached_tokens
            used[2] += call.output_tokens
    return {"calls": dict(Counter(f"{c.provider}:{c.purpose}" for c in manifest.calls)),
            "failed_calls": sum(c.error is not None for c in manifest.calls),
            "tokens_by_model": tokens,
            "latency_ms": sum(c.latency_ms or 0 for c in manifest.calls),
            "errors": len(manifest.errors), "rejections": len(manifest.rejections),
            "skipped_by_router": manifest.skipped_by_router,
            "compression_fallbacks": manifest.compression_fallbacks,
            "embedding_search": manifest.embedding_search}


def run_rows(rows: Iterable[dict], one: Callable[[dict, Callable], dict], make_llm: Callable,
             max_calls: int) -> Iterable[dict]:
    """Run `one` on each row until the call budget is used up. Later rows are marked not run."""
    left = max_calls
    for row in rows:
        made: list[Budgeted] = []

        def factory(manifest: RunManifest) -> Budgeted:
            made.append(Budgeted(make_llm(manifest), left))
            return made[-1]

        if left <= 0:
            empty = RunManifest(analysis_id="", mode=Mode.frozen, config_hash="")
            yield {"id": row["id"], "status": "not_run", "score": None, **_usage(empty)}
            continue
        prediction = one(row, factory)
        left -= sum(llm.calls for llm in made)
        if any(llm.refused for llm in made):
            # A call was refused during this example, so its result is not a prediction.
            prediction["status"] = "not_run"
        yield prediction


def detect(row: dict, llm_factory: Callable, router: Router | None = None) -> dict:
    """Claim detection: does the extractor find a checkable assertion in the sentence."""
    manifest = RunManifest(analysis_id=str(row["id"]), mode=Mode.frozen, config_hash="")
    span = SourceSpan(id=str(row["id"]), document_id="dataset", kind="paragraph",
                      text=row["text"], start=0, end=len(row["text"]))
    claims = extract([span], llm_factory(manifest), router, manifest)
    # A provider failure is not a negative prediction, so the example is left out of the score.
    return {"id": row["id"], "predicted": bool(claims),
            "status": "not_run" if manifest.errors else "ran", **_usage(manifest)}


def verify(row: dict, llm_factory: Callable, searchable: dict[str, list[dict]],
           task: VerificationTask, system: str, settings: Settings, router=None,
           compressor=None) -> dict:
    """A new store and index for the example, holding only its own searchable documents."""
    store, index = Store("sqlite://"), MemoryIndex()
    text = row[task.text_field]
    document, _ = admit(store, text.encode(), "text/plain")
    for source in searchable.get(str(row["id"]), []):
        published = source.get("published_at")
        snapshot, spans = admit(store, source["content"].encode(),
                                source.get("media_type", "text/plain"), source.get("url"),
                                datetime.fromisoformat(published) if published else None)
        index.index(snapshot, spans)
    deps = Deps(store=store, index=index, llm_factory=llm_factory, router=router,
                compressor=compressor, target=task.target,
                settings=settings if system == "A1" else settings_for(system, settings))
    score = None
    status: str
    if system == "A1":
        manifest = RunManifest(analysis_id=str(row["id"]), mode=Mode.frozen, config_hash="")
        claim = Claim(id=str(row["id"]), document_id=document.id, span_id="", text=text,
                      start=0, end=len(text), assertion_type=AssertionType.reported_achievement)
        try:
            status = retrieve_then_judge(llm_factory(manifest), index, store, claim).status
        except ProviderError as exc:
            manifest.errors.append(str(exc))
            status = "not_run"
        manifest.embedding_search = getattr(index, "used_embeddings", None)
    else:
        store.put("analyses", "run", {"id": "run", "document_id": document.id,
                                      "status": "queued"}, document_id=document.id)
        run_analysis("run", deps)
        manifest = RunManifest.model_validate(store.get("manifests", "run"))
        findings = store.find("findings", Finding, analysis_id="run")
        states = store.find("states", InvestigationState, analysis_id="run")
        status = findings[0].evidence_status if findings else "no_claim_extracted"
        failed = store.get("analyses", "run")["status"] == "failed" or (
            not findings and manifest.errors) or any(
            s.stop_reason == "provider_error" for s in states)
        if failed:
            status = "not_run"  # a provider failure is not a prediction
        elif states and states[0].belief:
            score = states[0].belief.raw_probability
    target = task.target(Claim(id="", document_id="", span_id="", text="", start=0, end=0,
                               assertion_type=AssertionType.reported_achievement), None)
    return {"id": row["id"], "system": system, "updater": deps.settings.assessment.updater,
            "status": status, "score": score, "target": target.id, **_usage(manifest)}


def _cost(predictions: list[dict], prices: dict[str, list[float]] | None) -> float | str:
    used: dict[str, list[int]] = {}
    for p in predictions:
        for model, counts in p["tokens_by_model"].items():
            used[model] = [a + b for a, b in zip(used.get(model, [0, 0, 0]), counts)]
    providers = {key.split(":")[0] for p in predictions for key in p["calls"]}
    if prices is None or set(used) - set(prices) or providers - {"openai"}:
        # A model price is missing, or Jev or Token Company usage has no price here. A figure
        # for the OpenAI part alone would make routing and compression look cheaper than they are.
        return "unknown"
    return sum(n * rate for model, counts in used.items() for n, rate in zip(counts, prices[model]))


def score(predictions: list[dict], gold: list[dict], task: VerificationTask | None,
          prices: dict[str, list[float]] | None = None) -> dict:
    usable = (lambda label: label in task.status_of) if task else (lambda label: label is not None)
    labels = {str(g["id"]): g["label"] for g in gold if usable(g["label"])}
    ran = [p for p in predictions if str(p["id"]) in labels and p["status"] != "not_run"]
    result = {"examples": len(predictions), "scored": len(ran),
              "gold_rows_without_a_usable_label": len(gold) - len(labels),
              "cost": _cost(predictions, prices),
              "calls": dict(sum((Counter(p["calls"]) for p in predictions), Counter())),
              "failed_calls": sum(p["failed_calls"] for p in predictions),
              "latency_ms": sum(p["latency_ms"] for p in predictions),
              "skipped_by_router": sum(p["skipped_by_router"] for p in predictions),
              "compression_fallbacks": sum(p["compression_fallbacks"] for p in predictions)}
    if task is None:
        precision, recall = precision_recall([p["predicted"] for p in ran],
                                             [bool(labels[str(p["id"])]) for p in ran])
        return {**result, "precision": precision, "recall": recall}
    targets = {p.get("target") for p in ran}
    result["target"] = sorted(map(str, targets))
    expected = [task.status_of[labels[str(p["id"])]] for p in ran]
    result["status_agreement"] = (sum(p["status"] == e for p, e in zip(ran, expected)) / len(ran)
                                  if ran else None)
    result["confusion"] = dict(Counter(f"{e} -> {p['status']}" for p, e in zip(ran, expected)))
    # Scores for different targets are not comparable, so they are not pooled.
    scored = [(p["score"], int(labels[str(p["id"])] == task.positive)) for p in ran
              if p["score"] is not None and len(targets) == 1]
    # Score metrics cover only the examples that have a score. Without any, they do not exist.
    result["with_score"] = len(scored)
    values, outcomes = [s for s, _ in scored], [y for _, y in scored]
    result["brier"] = brier(values, outcomes) if scored else "unavailable"
    result["nll"] = nll(values, outcomes) if scored else "unavailable"
    return result


def _read(path: str, limit: int | None = None) -> list[dict]:
    rows = list(read_rows(path))
    return rows[:limit] if limit else rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["detect", "verify", "score"])
    parser.add_argument("--visible")
    parser.add_argument("--searchable")
    parser.add_argument("--gold")
    parser.add_argument("--predictions")
    parser.add_argument("--out", required=True)
    parser.add_argument("--dataset", choices=sorted(VERIFICATION))
    parser.add_argument("--system", choices=["A1", *ABLATIONS], default="A2")
    parser.add_argument("--updater", choices=["linguistic", "full_context", "evidence_accumulator"])
    parser.add_argument("--jev", action="store_true")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--max-calls", type=int, default=200)
    parser.add_argument("--prices")
    args = parser.parse_args()
    needed = {"detect": ["visible"], "verify": ["visible", "dataset"],
              "score": ["predictions", "gold"]}[args.command]
    missing = [f"--{name}" for name in needed if not getattr(args, name)]
    if missing:
        parser.error(f"{args.command} needs {', '.join(missing)}")  # before any file is written
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    task = VERIFICATION.get(args.dataset or "")
    if args.command == "score":
        prices = json.loads(Path(args.prices).read_text()) if args.prices else None
        result = score(_read(args.predictions), _read(args.gold), task, prices)
        out.write_text(json.dumps({"predictions": args.predictions, "dataset": args.dataset,
                                   **result}, indent=2))
        print(json.dumps(result, indent=2))
        return

    from backend.providers.openai_client import OpenAILLM
    settings = load_settings("config/evaluation.yaml")
    if args.updater:
        settings.assessment.updater = args.updater
    router = compressor = None
    if args.jev or args.system in ("A3", "A5"):
        from backend.providers.jev import JevRouter
        router = JevRouter()
    if args.system in ("A4", "A5"):
        from backend.providers.ttc import TokenCompanyCompressor
        compressor = TokenCompanyCompressor()
    if args.command == "detect":
        def one(row, factory):
            return detect(row, factory, router)
    else:
        sources: dict[str, list[dict]] = {}
        for source in _read(args.searchable) if args.searchable else []:
            sources.setdefault(str(source["example_id"]), []).append(source)

        def one(row, factory):
            return verify(row, factory, sources, task, args.system, settings, router, compressor)
    out.with_suffix(".meta.json").write_text(json.dumps({
        "command": args.command, "system": args.system, "jev": bool(router),
        "commit": current_commit(), "config": settings.config_hash(),
        "max_calls": args.max_calls, "limit": args.limit}, indent=2))
    with out.open("w", encoding="utf-8") as handle:
        for prediction in run_rows(_read(args.visible, args.limit), one, OpenAILLM, args.max_calls):
            handle.write(json.dumps(prediction, default=str) + "\n")

if __name__ == "__main__":
    main()
