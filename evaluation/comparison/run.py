"""Compare the structured pipeline with two single-prompt systems on cases with known answers.

Usage: uv run --env-file .env python -m evaluation.comparison.run --out results/comparison.json
           [--arms pipeline chatgpt devin] [--only CASE_ID ...] [--repeats 1]
           [--updater linguistic] [--max-calls 50000] [--devin-max-acu 5]
           [--devin-timeout 1800] [--devin-parallel 4]

Every arm reads the same parsed passages and returns the same output format. The scorer is code:
it reads each case's expected answer, which no arm is given. The pipeline and chatgpt arms make
paid OpenAI calls, bounded by --max-calls. The devin arm starts one paid Devin session per case
and repeat, each bounded by --devin-max-acu. It needs DEVIN_API_KEY and DEVIN_ORG_ID.
A Markdown table is written next to the JSON result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from backend.config import Settings, env, load_settings
from backend.models import RunManifest
from backend.orchestration.worker import current_commit
from backend.providers.base import ProviderError
from evaluation.budget import Budgeted
from evaluation.comparison import arms
from evaluation.comparison.schema import PROMPT, Case
from evaluation.comparison.score import score, summarise

ARMS = ["pipeline", "chatgpt", "devin"]
CASES = Path(__file__).with_name("cases.json")


def load_cases(path: str | Path = CASES, only: list[str] | None = None) -> list[Case]:
    cases = [Case.model_validate(c) for c in json.loads(Path(path).read_text())["cases"]]
    return [c for c in cases if not only or c.id in only]


def _one(case: Case, repeat: int, call: Callable) -> dict:
    """Run one arm on one case and score it. A provider failure is recorded, not scored."""
    prepared = arms.Prepared(case)
    started = time.monotonic()
    row = {"case": case.id, "category": case.category, "repeat": repeat, "error": None,
           "usage": {}}
    try:
        output, row["usage"] = call(prepared)
        row.update(score(case, prepared.passages, output), output=output.model_dump(mode="json"))
    except ProviderError as exc:
        row["error"] = str(exc)
    row["seconds"] = round(time.monotonic() - started, 1)
    return row


def run(cases: list[Case], names: list[str], repeats: int, make_llm: Callable, settings: Settings,
        max_calls: int, devin_options: dict | None = None, devin_parallel: int = 4) -> dict:
    left = max_calls
    result: dict = {}
    jobs = [(case, repeat) for case in cases for repeat in range(repeats)]
    for name in (n for n in names if n != "devin"):
        rows = []
        for case, repeat in jobs:
            made: list[Budgeted] = []

            def factory(manifest: RunManifest) -> Budgeted:
                made.append(Budgeted(make_llm(manifest), left))
                return made[-1]

            if left <= 0:
                rows.append({"case": case.id, "category": case.category, "repeat": repeat,
                             "error": "not run: the call budget is used up", "usage": {},
                             "seconds": 0})
                continue
            call = (lambda p: arms.pipeline(p, factory, settings)) if name == "pipeline" \
                else (lambda p: arms.chatgpt(p, factory))
            row = _one(case, repeat, call)
            left -= sum(llm.calls for llm in made)
            if any(llm.refused for llm in made):
                row["error"] = "not scored: a call was refused by the call budget"
            rows.append(row)
        result[name] = {"available": True, "rows": rows}
    if "devin" in names:
        if env("DEVIN_API_KEY") and env("DEVIN_ORG_ID"):
            with ThreadPoolExecutor(devin_parallel) as pool:
                rows = list(pool.map(lambda job: _one(
                    job[0], job[1], lambda p: arms.devin(p, **(devin_options or {}))), jobs))
            result["devin"] = {"available": True, "rows": rows}
        else:
            result["devin"] = {"available": False, "rows": [],
                               "reason": "DEVIN_API_KEY and DEVIN_ORG_ID must both be set"}
    for arm in result.values():
        arm["summary"] = summarise(arm["rows"])
        arm["status_correct_by_category"] = {
            category: summarise([r for r in arm["rows"] if r["category"] == category])["status_correct"]
            for category in sorted({c.category for c in cases})}
    return {"commit": current_commit(), "prompt_sha256": hashlib.sha256(PROMPT.encode()).hexdigest()[:16],
            "models": {"extract": env("OPENAI_EXTRACT_MODEL"), "reason": env("OPENAI_REASON_MODEL"),
                       "effort": env("OPENAI_REASONING_EFFORT")},
            "updater": settings.assessment.updater, "repeats": repeats,
            "openai_calls_used": max_calls - left, "max_calls": max_calls,
            "cases": {c.id: {"category": c.category, "accept": c.expected.accept_statuses}
                      for c in cases},
            "arms": result}


def _cell(value) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def markdown(result: dict) -> str:
    names = list(result["arms"])
    lines = ["# Comparison: structured pipeline and single-prompt systems", "",
             f"Commit {result['commit']}. {len(result['cases'])} synthetic cases, "
             f"{result['repeats']} run(s) per case. OpenAI models: {result['models']}. "
             f"Pipeline updater: {result['updater']}. Every arm read the same parsed passages. "
             "The scorer is code. A rate leaves out the cases in which an arm did not run.", ""]
    for name, arm in result["arms"].items():
        if not arm["available"]:
            lines += [f"The {name} arm did not run: {arm['reason']}.", ""]
    rows = [("cases run", "cases_run"), ("cases failed to run", "cases_failed"),
            ("claim found (share of cases)", "claim_found"),
            ("status correct (share of cases)", "status_correct"),
            ("key numbers computed (share of key numbers)", "key_numbers_found"),
            ("quotes that are exact substrings (share of quotes)", "quotes_exact"),
            ("findings with no quote", "findings_without_a_quote"),
            ("numbers in the text found in no passage or reference calculation", "unverified_numbers"),
            ("findings that state a probability", "probability_stated"),
            ("findings other than the case's claim", "other_findings"),
            ("same status in every repeat (share of cases)", "same_status_across_repeats"),
            ("OpenAI calls", "calls"), ("input tokens", "input_tokens"),
            ("output tokens", "output_tokens"), ("Devin ACUs", "acus"), ("seconds", "seconds")]
    lines += ["| measure | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    lines += [f"| {label} | " + " | ".join(_cell(result["arms"][n]["summary"][key]) for n in names)
              + " |" for label, key in rows]
    lines += ["", "## Status by case", "",
              "| case | category | accepted | " + " | ".join(names) + " |",
              "|---|---|---|" + "---|" * len(names)]
    for case_id, case in result["cases"].items():
        cells = []
        for name in names:
            given = [r for r in result["arms"][name]["rows"] if r["case"] == case_id]
            cells.append(", ".join(f"not run ({r['error'][:40]})" if r["error"] else
                                   f"{r['status'] or 'claim not found'}"
                                   f" ({'correct' if r['status_correct'] else 'wrong'})"
                                   for r in given) or "not run")
        lines.append(f"| {case_id} | {case['category']} | {', '.join(case['accept'])} | "
                     + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    parser.add_argument("--arms", nargs="+", choices=ARMS, default=ARMS)
    parser.add_argument("--cases", default=str(CASES))
    parser.add_argument("--only", nargs="+")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--updater", choices=["linguistic", "full_context", "evidence_accumulator"])
    parser.add_argument("--max-calls", type=int, default=50000)
    parser.add_argument("--devin-max-acu", type=int, default=5)
    parser.add_argument("--devin-timeout", type=int, default=1800)
    parser.add_argument("--devin-parallel", type=int, default=4)
    args = parser.parse_args()
    from backend.providers.openai_client import OpenAILLM

    settings = load_settings("config/evaluation.yaml")
    if args.updater:
        settings.assessment.updater = args.updater
    result = run(load_cases(args.cases, args.only), args.arms, args.repeats, OpenAILLM, settings,
                 args.max_calls, {"max_acu": args.devin_max_acu, "timeout_s": args.devin_timeout},
                 args.devin_parallel)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, default=str))
    out.with_suffix(".md").write_text(markdown(result))
    print(markdown(result))


if __name__ == "__main__":
    main()
