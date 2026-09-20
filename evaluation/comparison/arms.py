"""The three systems under comparison. Each gets the same parsed passages and returns AuditOutput.

pipeline  the structured Countercheck investigation
chatgpt   one call to the same OpenAI reasoning model with one prompt
devin     one Devin session (v3 API) with the same prompt

No arm is given a case's expected answer.
"""
from __future__ import annotations

import json
import time
from typing import Callable

import httpx
from pydantic import ValidationError

from backend.config import Settings
from backend.db import Store
from backend.ingestion.snapshot import admit
from backend.models import Claim, Finding, InvestigationState, Mode, RunManifest, SourceSpan
from backend.orchestration.worker import Deps, run_analysis
from backend.providers.devin import run_session
from backend.retrieval.memory import MemoryIndex
from evaluation.comparison.schema import (
    PROMPT, AuditFinding, AuditNumber, AuditOutput, AuditQuote, Case,
)



class NoAnswer(Exception):
    """The system ran and returned nothing usable. It is scored as a miss and its cost counts.

    A ProviderError, by contrast, means the system could not be run: an outage, a missing key, or
    the call budget. Those cases are left out of the rates.
    """

    def __init__(self, message: str, usage: dict) -> None:
        super().__init__(message)
        self.usage = usage


class Prepared:
    """One case parsed once, so that every arm reads exactly the same passage text."""

    def __init__(self, case: Case) -> None:
        self.store, self.index = Store("sqlite://"), MemoryIndex()
        self.passages: dict[str, list[SourceSpan]] = {}
        self.audited = ""
        for document in case.documents:
            snapshot, spans = admit(self.store, document.content.encode(), document.media_type)
            self.index.index(snapshot, spans)
            self.passages[snapshot.id] = spans
            if document.role == "audited":
                self.audited = snapshot.id

    def payload(self) -> dict:
        def shown(document_id: str) -> dict:
            return {"document_id": document_id,
                    "passages": [{"id": s.id, "text": s.text} for s in self.passages[document_id]]}
        return {"audited_document": shown(self.audited),
                "other_documents": [shown(d) for d in self.passages if d != self.audited]}


def _usage(manifest: RunManifest) -> dict:
    calls = [c for c in manifest.calls if c.provider == "openai"]
    return {"calls": len(calls), "partial": bool(manifest.errors), "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls), "errors": manifest.errors}


def pipeline(prepared: Prepared, llm_factory: Callable, settings: Settings) -> tuple[AuditOutput, dict]:
    store = prepared.store
    store.put("analyses", "run", {"id": "run", "document_id": prepared.audited, "status": "queued"},
              document_id=prepared.audited)
    run_analysis("run", Deps(store=store, index=prepared.index, llm_factory=llm_factory,
                             settings=settings))
    manifest = RunManifest.model_validate(store.get("manifests", "run"))
    job = store.get("analyses", "run") or {}
    if job.get("status") != "complete":
        # The job stopped on an error of its own. That is a result of the system, not an outage.
        raise NoAnswer(f"pipeline run was {job.get('status')}: {manifest.errors}", _usage(manifest))
    states = {s.claim.id: s for s in store.find("states", InvestigationState, analysis_id="run")}
    findings = []
    for finding in store.find("findings", Finding, analysis_id="run"):
        state = states[finding.claim_id]
        claim = store.get("claims", finding.claim_id, Claim)
        findings.append(AuditFinding(
            claim_quote=claim.text if claim else "", status=finding.evidence_status.value,
            summary=finding.summary, supported_rewrite=finding.supported_rewrite,
            probability=finding.probability,
            evidence=[AuditQuote(document_id=e.document_id, quote=e.quote) for e in state.evidence],
            computed=[AuditNumber(name=name, value=str(value), unit=c.units.get(name, ""))
                      for c in state.calculations for name, value in c.outputs.items()]))
    usage = _usage(manifest)
    usage["rejections"] = manifest.rejections
    usage["limitations"] = [l for f in store.find("findings", Finding, analysis_id="run")
                            for l in f.uncertainty.measurement_limitations]
    return AuditOutput(findings=findings), usage


def chatgpt(prepared: Prepared, llm_factory: Callable) -> tuple[AuditOutput, dict]:
    manifest = RunManifest(analysis_id="chatgpt", mode=Mode.frozen, config_hash="")
    output = llm_factory(manifest).ask("baseline", PROMPT, prepared.payload(), AuditOutput)
    return output, _usage(manifest)


def devin(prepared: Prepared, client: httpx.Client | None = None, max_acu: int = 5,
          timeout_s: int = 1800, poll_s: float = 15, sleep=time.sleep) -> tuple[AuditOutput, dict]:
    prompt = (f"{PROMPT}\n\nReturn the findings as the structured output of this session. "
              "Do not write code and do not open a pull request.\n\nDocuments (JSON):\n"
              + json.dumps(prepared.payload()))
    session = run_session(prompt, AuditOutput.model_json_schema(), "Countercheck comparison",
                          max_acu, timeout_s, client, poll_s, sleep)
    usage = {"sessions": 1, "acus": session.acus, "session_url": session.url, "errors": []}
    if session.output is None:
        raise NoAnswer(f"devin {session.ended} without structured output", usage)
    try:
        return AuditOutput.model_validate(session.output), usage
    except ValidationError as exc:
        raise NoAnswer(f"devin {session.ended} with output in another format: "
                       f"{exc.error_count()} errors", usage) from exc
