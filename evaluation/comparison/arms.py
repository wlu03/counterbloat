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

from backend.config import Settings, env
from backend.db import Store
from backend.ingestion.snapshot import admit
from backend.models import Claim, Finding, InvestigationState, Mode, RunManifest, SourceSpan
from backend.orchestration.worker import Deps, run_analysis
from backend.providers.base import ProviderError
from backend.retrieval.memory import MemoryIndex
from evaluation.comparison.schema import (
    PROMPT, AuditFinding, AuditNumber, AuditOutput, AuditQuote, Case,
)

DEVIN_API = "https://api.devin.ai/v3/organizations"


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
    return {"calls": len(calls), "input_tokens": sum(c.input_tokens for c in calls),
            "output_tokens": sum(c.output_tokens for c in calls), "errors": manifest.errors}


def pipeline(prepared: Prepared, llm_factory: Callable, settings: Settings) -> tuple[AuditOutput, dict]:
    store = prepared.store
    store.put("analyses", "run", {"id": "run", "document_id": prepared.audited, "status": "queued"},
              document_id=prepared.audited)
    run_analysis("run", Deps(store=store, index=prepared.index, llm_factory=llm_factory,
                             settings=settings))
    manifest = RunManifest.model_validate(store.get("manifests", "run"))
    job = store.get("analyses", "run") or {}
    if job.get("status") != "complete" or job.get("partial"):
        raise ProviderError(f"pipeline run was {job.get('status')}: {manifest.errors}")
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
    return AuditOutput(findings=findings), _usage(manifest)


def chatgpt(prepared: Prepared, llm_factory: Callable) -> tuple[AuditOutput, dict]:
    manifest = RunManifest(analysis_id="chatgpt", mode=Mode.frozen, config_hash="")
    output = llm_factory(manifest).ask("baseline", PROMPT, prepared.payload(), AuditOutput)
    return output, _usage(manifest)


def _inlined(schema: dict) -> dict:
    """Devin wants a self-contained schema, so each $ref is replaced by what it points to."""
    definitions = schema.get("$defs", {})

    def resolve(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(definitions[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        return [resolve(v) for v in node] if isinstance(node, list) else node
    return resolve(schema)


def devin(prepared: Prepared, client: httpx.Client | None = None, max_acu: int = 5,
          timeout_s: int = 1800, poll_s: float = 15, sleep=time.sleep) -> tuple[AuditOutput, dict]:
    key, org = env("DEVIN_API_KEY"), env("DEVIN_ORG_ID")
    if not (key and org):
        raise ProviderError("DEVIN_API_KEY and DEVIN_ORG_ID must be set")
    client = client or httpx.Client(timeout=60)
    headers = {"Authorization": f"Bearer {key}"}
    body = {"prompt": f"{PROMPT}\n\nReturn the findings as the structured output of this session. "
                      "Do not write code and do not open a pull request.\n\nDocuments (JSON):\n"
                      + json.dumps(prepared.payload()),
            "title": "Countercheck comparison", "tags": ["countercheck-comparison"],
            "structured_output_required": True, "max_acu_limit": max_acu,
            "structured_output_schema": _inlined(AuditOutput.model_json_schema())}
    started = time.monotonic()
    try:
        created = client.post(f"{DEVIN_API}/{org}/sessions", json=body, headers=headers)
        created.raise_for_status()
        session_id = created.json()["session_id"]
        while True:
            answer = client.get(f"{DEVIN_API}/{org}/sessions/{session_id}", headers=headers)
            answer.raise_for_status()
            session = answer.json()
            waiting = session["status"] in ("new", "claimed", "resuming") or (
                session["status"] == "running" and session.get("status_detail") == "working")
            if not waiting:
                break
            if time.monotonic() - started > timeout_s:
                raise ProviderError(f"devin session {session_id} did not finish in {timeout_s} s")
            sleep(poll_s)
    except (httpx.HTTPError, KeyError) as exc:
        raise ProviderError(f"devin request failed: {exc}") from exc
    usage = {"calls": 1, "acus": session.get("acus_consumed"), "session_url": session.get("url"),
             "errors": []}
    if not session.get("structured_output"):
        raise ProviderError(f"devin session {session_id} ended without structured output: "
                            f"{session['status']} {session.get('status_detail')}")
    return AuditOutput.model_validate(session["structured_output"]), usage
