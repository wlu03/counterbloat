"""One budgeted live run of the fictional emissions example through the real providers.

Usage: uv run --env-file .env python -m evaluation.smoke --out results/smoke.json
           [--updater evidence_accumulator] [--max-calls 25]

This makes paid OpenAI calls. The run stops making calls once --max-calls is reached.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.config import load_settings
from backend.db import Store
from backend.ingestion.snapshot import admit
from backend.models import Finding, InvestigationState
from backend.orchestration.worker import Deps, run_analysis
from backend.retrieval.memory import MemoryIndex
from evaluation.budget import Budgeted

DOCUMENT = Path("evaluation/fixtures/emissions_report.html")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", required=True)
    parser.add_argument("--updater", default="evidence_accumulator")
    parser.add_argument("--max-calls", type=int, default=25)
    args = parser.parse_args()
    from backend.providers.openai_client import OpenAILLM

    settings = load_settings("config/evaluation.yaml")
    settings.assessment.updater = args.updater
    store, index = Store("sqlite://"), MemoryIndex()
    llms: list[Budgeted] = []

    def factory(manifest):
        llms.append(Budgeted(OpenAILLM(manifest), args.max_calls))
        return llms[-1]

    snapshot, spans = admit(store, DOCUMENT.read_bytes(), "text/html")
    index.index(snapshot, spans)
    store.put("analyses", "smoke", {"id": "smoke", "document_id": snapshot.id, "status": "queued"},
              document_id=snapshot.id)
    run_analysis("smoke", Deps(store=store, index=index, settings=settings, llm_factory=factory))
    findings = store.find("findings", Finding, analysis_id="smoke")
    states = store.find("states", InvestigationState, analysis_id="smoke")
    assert all(f.probability is None for f in findings), "a finding carries a public probability"
    result = {"is_synthetic_example": True, "job": store.get("analyses", "smoke"),
              "calls_made": sum(llm.calls for llm in llms), "max_calls": args.max_calls,
              "findings": [f.model_dump(mode="json") for f in findings],
              "internal": [{"claim": s.claim.text, "target": s.target.id,
                            "belief": s.belief.model_dump(mode="json") if s.belief else None,
                            "calculations": [c.model_dump(mode="json") for c in s.calculations]}
                           for s in states],
              "manifest": store.get("manifests", "smoke")}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, indent=2, default=str))
    for finding in findings:
        print(finding.evidence_status, "|", finding.summary)


if __name__ == "__main__":
    main()
