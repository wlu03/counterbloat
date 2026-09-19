"""Write one Markdown report from the result files of replays and scored experiments.

Usage: python -m evaluation.report RESULTS_DIR --out REPORT.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _show(value) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.4f}" if isinstance(value, float) else str(value)


def _replay(name: str, result: dict) -> list[str]:
    kind = "synthetic example" if result["is_synthetic_example"] else "recorded investigation"
    lines = [f"## Replay: {result['trace']} ({name})", "",
             f"Source: {result['source']} This is a {kind}. Provider: {result['provider']}. "
             f"Seed {result['seed']}, {result['permutations']} permutations, prior "
             f"{result['prior']}, tempering {result['tempering']}, commit {result['commit']}, "
             f"{result['paid_calls_used']} paid calls.", "",
             "| strategy | final status | raw score | order changes status | score range over "
             "orders | duplicate source | irrelevant addition | withdrawal | correction |",
             "|---|---|---|---|---|---|---|---|---|"]
    for strategy, outcome in result["strategies"].items():
        base, compared = outcome["runs"]["base"], outcome["comparison"]
        cells = [strategy, base["final_status"], _show(base["final_score"]),
                 _show(compared["order_changes_status"]), _show(compared["order_score_range"])]
        for variant in ("duplicate_source", "irrelevant_addition", "withdrawal", "correction"):
            change = compared.get(variant)
            cells.append("not run" if change is None else
                         f"status {'changed' if change['status_changed'] else 'same'}, "
                         f"score change {_show(change['score_change'])}")
        lines.append("| " + " | ".join(cells) + " |")
    return lines + [""]


def _scored(name: str, result: dict) -> list[str]:
    lines = [f"## Scored run: {name}", "", f"Predictions: {result['predictions']}.", ""]
    lines += [f"- {key}: {_show(value)}" for key, value in result.items() if key != "predictions"]
    return lines + [""]


def build(results_dir: str | Path) -> str:
    lines = ["# Countercheck evaluation report", "",
             "Raw scores are uncalibrated estimates for the target named in each run. "
             "A value shown as unavailable was not produced. It is not zero.", ""]
    for path in sorted(Path(results_dir).glob("*.json")):
        result = json.loads(path.read_text())
        if "strategies" in result:
            lines += _replay(path.name, result)
        elif "scored" in result:
            lines += _scored(path.name, result)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_dir")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    Path(args.out).write_text(build(args.results_dir))


if __name__ == "__main__":
    main()
