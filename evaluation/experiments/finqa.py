"""FinQA: does the answer come out right when code does the arithmetic instead of the model.

Both arms read the same passages, parsed by this repository's HTML parser so the table columns
carry their headers. They differ in who computes:

  program   the model names the figures and the operations; the calculator runs them, and refuses
            an input that is not written in the passage it cites
  direct    the model states the answer itself and lists the figures it says it used

    python -m evaluation.experiments.finqa run --arm program --limit 100 --seed 3 --out P.jsonl
    python -m evaluation.experiments.finqa score --predictions P.jsonl --out R.json

run never opens the gold file. It calls OpenAI, which is paid, so --max-calls bounds the run.
"""
from __future__ import annotations

import argparse
import json
import random
import re
from decimal import Decimal, InvalidOperation
from html import escape
from pathlib import Path
from typing import Callable, Iterable

from backend.db import Store
from backend.ingestion.snapshot import admit
from backend.models import CalcInput, Mode, RunManifest, SourceSpan
from backend.orchestration.worker import current_commit
from backend.providers.base import ProviderError
from backend.verification.numeric import CalculationError, execute, parse_number, value_in_source
from evaluation.budget import Budgeted
from evaluation.experiments.run import _usage

INPUTS = Path("datasets/finqa/runtime/inputs.jsonl")
GOLD = Path("datasets/finqa/evaluator_only/references.jsonl")
# FinQA answers are rounded to a few places, and a percentage may be written as 14.1 or 0.141.
TOLERANCE = Decimal("0.02")


def document(row: dict) -> bytes:
    """The example as one HTML document: its text, and its table as a table."""
    def lines(value) -> list[str]:
        return value if isinstance(value, list) else [str(value)]

    table = ""
    if row.get("table"):
        cells = "".join(
            "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in line) + "</tr>"
            for line in row["table"])
        table = f"<table>{cells}</table>"
    body = "".join(f"<p>{escape(t)}</p>" for t in lines(row.get("pre_text", [])) if t.strip())
    tail = "".join(f"<p>{escape(t)}</p>" for t in lines(row.get("post_text", [])) if t.strip())
    return f"<html><body>{body}{table}{tail}</body></html>".encode()


def passages(row: dict, store: Store) -> list[SourceSpan]:
    snapshot, spans = admit(store, document(row), "text/html")
    return spans


def context(spans: list[SourceSpan]) -> str:
    return "\n\n".join(f"[{s.id}] {s.text}" for s in spans)


def _grounded(value: str, span_id: str, spans: dict[str, SourceSpan]) -> bool:
    """Whether the figure is written in the passage it was attributed to."""
    span = spans.get(span_id)
    try:
        return span is not None and value_in_source(parse_number(value), span)
    except CalculationError:
        return False


def program_arm(row: dict, llm_factory: Callable) -> dict:
    """The model names the figures and the operations. The calculator runs them."""
    manifest = RunManifest(analysis_id=str(row["example_id"]), mode=Mode.frozen, config_hash="")
    store = Store("sqlite://")
    spans = passages(row, store)
    by_id = {s.id: s for s in spans}
    answer, grounded, cited, note = None, 0, 0, ""
    try:
        draft = llm_factory(manifest).propose_program(row["question"], context(spans))
        cited = len(draft.inputs)
        grounded = sum(_grounded(i.value, i.source_span_id, by_id) for i in draft.inputs)
        inputs = [CalcInput(**i.model_dump(exclude={"value"}), value=parse_number(i.value))
                  for i in draft.inputs]
        for value in inputs:
            span = by_id.get(value.source_span_id)
            if span is None or not value_in_source(value.value, span):
                raise CalculationError(f"input {value.name} is not in the passage it cites")
        if not draft.steps:
            # The answer is written in a passage, so there is nothing to compute. It is still
            # only accepted because the guard above found it in the passage it cites.
            if len(inputs) != 1:
                raise CalculationError("a program with no operation must read exactly one figure")
            answer, note = str(inputs[0].value), draft.note
        else:
            result = execute("q", "q", inputs, draft.steps, draft.note)
            name = draft.claim_output if draft.claim_output in result.outputs else draft.steps[-1].out
            answer, note = str(result.outputs[name]), draft.note
    except (CalculationError, ValueError, IndexError) as exc:
        manifest.rejections.append(f"program rejected: {exc}")
    except ProviderError as exc:
        manifest.errors.append(str(exc))
    return {"id": row["example_id"], "arm": "program", "answer": answer, "note": note,
            "cited": cited, "grounded": grounded,
            "status": "not_run" if manifest.errors else "ran", **_usage(manifest)}


def direct_arm(row: dict, llm_factory: Callable) -> dict:
    """The model states the answer itself."""
    manifest = RunManifest(analysis_id=str(row["example_id"]), mode=Mode.frozen, config_hash="")
    store = Store("sqlite://")
    spans = passages(row, store)
    by_id = {s.id: s for s in spans}
    answer, grounded, cited, note = None, 0, 0, ""
    try:
        given = llm_factory(manifest).answer_directly(row["question"], context(spans))
        cited = len(given.inputs)
        grounded = sum(_grounded(i.value, i.source_span_id, by_id) for i in given.inputs)
        answer, note = given.answer, given.note
    except ProviderError as exc:
        manifest.errors.append(str(exc))
    return {"id": row["example_id"], "arm": "direct", "answer": answer, "note": note,
            "cited": cited, "grounded": grounded,
            "status": "not_run" if manifest.errors else "ran", **_usage(manifest)}


def _decimal(text) -> Decimal | None:
    try:
        return Decimal(re.sub(r"[^0-9.\-]", "", str(text)))
    except (InvalidOperation, ValueError):
        return None


def correct(answer, expected) -> bool:
    """FinQA stores a percentage as a fraction, 0.141 for 14.1 per cent, so when the expected
    value is below one the percentage form is accepted too. Above one it is not, because 0.94
    is not an answer of 94."""
    got, want = _decimal(answer), _decimal(expected)
    if got is None or want is None:
        return False
    allowed = [want] + ([want * 100] if abs(want) < 1 else [])
    return any(abs(abs(got) - abs(w)) <= TOLERANCE for w in allowed)


def score(predictions: list[dict], gold: list[dict]) -> dict:
    expected = {str(g["example_id"]): g.get("exe_ans") for g in gold}
    ran = [p for p in predictions if p["status"] != "not_run" and str(p["id"]) in expected]
    answered = [p for p in ran if p["answer"] is not None]
    right = [p for p in answered if correct(p["answer"], expected[str(p["id"])])]
    cited = sum(p["cited"] for p in ran)
    calls = sum(sum(p["calls"].values()) for p in predictions)
    return {
        "examples": len(predictions), "scored": len(ran),
        # The share of examples that produced an answer at all. The calculator refuses a program
        # whose figures are not in the passages they cite, and that example has no answer.
        "answered": len(answered),
        "accuracy_over_scored": len(right) / len(ran) if ran else None,
        "accuracy_over_answered": len(right) / len(answered) if answered else None,
        # The share of cited figures that are written in the passage they were attributed to.
        "figures_cited": cited,
        "figures_grounded": sum(p["grounded"] for p in ran),
        "grounding": sum(p["grounded"] for p in ran) / cited if cited else None,
        "rejected_programs": sum(p["rejections"] for p in ran),
        "calls": calls, "failed_calls": sum(p["failed_calls"] for p in predictions),
        "latency_ms": sum(p["latency_ms"] for p in predictions),
        "tokens": sum(sum(c) for p in predictions for c in p["tokens_by_model"].values()),
    }


def run_rows(rows: Iterable[dict], arm: Callable, make_llm: Callable, max_calls: int) -> Iterable[dict]:
    left = max_calls
    for row in rows:
        made: list[Budgeted] = []

        def factory(manifest: RunManifest) -> Budgeted:
            made.append(Budgeted(make_llm(manifest), left))
            return made[-1]

        if left <= 0:
            empty = RunManifest(analysis_id="", mode=Mode.frozen, config_hash="")
            yield {"id": row["example_id"], "arm": "", "answer": None, "note": "", "cited": 0,
                   "grounded": 0, "status": "not_run", **_usage(empty)}
            continue
        prediction = arm(row, factory)
        left -= sum(llm.calls for llm in made)
        if any(llm.refused for llm in made):
            prediction["status"] = "not_run"
        yield prediction


def _read(path: Path, limit: int | None = None, seed: int | None = None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if seed is not None and limit and limit < len(rows):
        return random.Random(seed).sample(rows, limit)
    return rows[:limit] if limit else rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "score"])
    parser.add_argument("--arm", choices=["program", "direct"], default="program")
    parser.add_argument("--inputs", default=str(INPUTS))
    parser.add_argument("--gold", default=str(GOLD))
    parser.add_argument("--predictions")
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--seed", type=int, default=3)
    parser.add_argument("--max-calls", type=int, default=400)
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.command == "score":
        result = score(_read(Path(args.predictions)), _read(Path(args.gold)))
        out.write_text(json.dumps({"predictions": args.predictions, **result}, indent=2))
        print(json.dumps(result, indent=2))
        return

    from backend.providers.openai_client import OpenAILLM

    arm = program_arm if args.arm == "program" else direct_arm
    out.with_suffix(".meta.json").write_text(json.dumps(
        {"arm": args.arm, "commit": current_commit(), "limit": args.limit, "seed": args.seed,
         "max_calls": args.max_calls}, indent=2))
    with out.open("w", encoding="utf-8") as handle:
        for prediction in run_rows(_read(Path(args.inputs), args.limit, args.seed), arm,
                                   OpenAILLM, args.max_calls):
            handle.write(json.dumps(prediction, default=str) + "\n")


if __name__ == "__main__":
    main()
