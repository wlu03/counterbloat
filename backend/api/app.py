"""HTTP API (specification section 13.3). Every endpoint defined here requires the application key."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import AwareDatetime, BaseModel

from backend.belief.priority import coverage
from backend.config import env, load_settings
from backend.db import Store
from backend.ingestion.fetch import BlockedDestination, FetchError
from backend.ingestion.snapshot import admit, admit_url, normalized_text
from backend.models import (
    BeliefUpdate, Claim, DocumentSnapshot, EvidenceItem, Finding, InvestigationState, Mode,
    ReviewState, SourceSpan,
)
from backend.orchestration.worker import Deps, run_analysis
from backend.providers.base import ProviderError
from backend.retrieval.memory import MemoryIndex


class DocumentRequest(BaseModel):
    url: str | None = None
    content: str | None = None
    media_type: Literal["text/html", "application/xhtml+xml", "text/plain",
                        "application/pdf"] = "text/html"
    # A date without a UTC offset cannot be compared with a cutoff, so it is refused.
    published_at: AwareDatetime | None = None


class AnalysisRequest(BaseModel):
    document_id: str
    mode: Mode | None = None
    cutoff: AwareDatetime | None = None
    selected_span_ids: list[str] = []
    # Run the code of a repository that the document links to, in one paid Devin session.
    replicate: bool = False


class ReviewRequest(BaseModel):
    reviewer: str
    decision: Literal["accept", "reject"]
    note: str = ""


def default_deps() -> Deps:
    from backend.providers.openai_client import OpenAILLM

    settings = load_settings(env("COUNTERCHECK_CONFIG") or "config/app.yaml")
    store = Store(env("DATABASE_URL", "sqlite:///countercheck.db"))
    if env("ELASTICSEARCH_URL"):
        from backend.retrieval.elastic import ElasticIndex
        try:
            index = ElasticIndex(OpenAILLM())
        except ProviderError:
            index = ElasticIndex()
    else:
        index = MemoryIndex()
    router = compressor = transcribe = None
    try:
        transcribe = OpenAILLM().transcribe
    except ProviderError:
        pass  # without OpenAI, an image-only PDF keeps the no_text_layer flag
    if env("TYPESAFE_API_KEY"):
        from backend.providers.jev import JevRouter
        router = JevRouter()
    if env("TTC_API_KEY"):
        from backend.providers.ttc import TokenCompanyCompressor
        compressor = TokenCompanyCompressor()
    replicator = None
    if env("DEVIN_API_KEY") and env("DEVIN_ORG_ID"):
        from backend.replication.replicate import replicate
        replicator = replicate
    return Deps(store=store, index=index, settings=settings, llm_factory=OpenAILLM,
                router=router, compressor=compressor, transcribe=transcribe,
                replicator=replicator)


def create_app(deps: Deps | None = None) -> FastAPI:
    app = FastAPI(title="Countercheck")
    state: dict[str, Deps] = {}

    def get_deps() -> Deps:
        if "deps" not in state:
            state["deps"] = deps or default_deps()
        return state["deps"]

    def authorize(x_api_key: str | None = Header(default=None)) -> None:
        expected = env("COUNTERCHECK_API_KEY")
        if not expected:
            raise HTTPException(503, "COUNTERCHECK_API_KEY is not configured")
        if x_api_key != expected:
            raise HTTPException(401, "invalid API key")

    def found(record, what: str):
        if record is None:
            raise HTTPException(404, f"{what} not found")
        return record

    guard = [Depends(authorize)]

    @app.post("/documents", dependencies=guard)
    def create_document(request: DocumentRequest, d: Deps = Depends(get_deps)):
        try:
            if request.url:
                snapshot, spans = admit_url(d.store, request.url, published_at=request.published_at,
                                            transcribe=d.transcribe)
            elif request.content:
                snapshot, spans = admit(d.store, request.content.encode(), request.media_type,
                                        published_at=request.published_at,
                                        transcribe=d.transcribe)
            else:
                raise HTTPException(422, "provide url or content")
        except (FetchError, BlockedDestination, ProviderError) as exc:
            raise HTTPException(400, str(exc)) from exc
        d.index.index(snapshot, spans)
        return snapshot

    @app.get("/documents/{document_id}", dependencies=guard)
    def read_document(document_id: str, d: Deps = Depends(get_deps)):
        snapshot = found(d.store.get("documents", document_id, DocumentSnapshot), "document")
        return {"snapshot": snapshot, "text": normalized_text(snapshot),
                "spans": d.store.find("spans", SourceSpan, document_id=document_id)}

    @app.post("/analyses", dependencies=guard)
    def create_analysis(request: AnalysisRequest, tasks: BackgroundTasks,
                        idempotency_key: str | None = Header(default=None),
                        d: Deps = Depends(get_deps)):
        found(d.store.get("documents", request.document_id), "document")
        if idempotency_key:
            existing = d.store.find("analyses", idempotency_key=idempotency_key)
            if existing:
                if existing[0]["document_id"] != request.document_id:
                    raise HTTPException(409, "Idempotency-Key was used for another document")
                return existing[0]
        job = {"id": f"an-{uuid.uuid4().hex[:12]}", "document_id": request.document_id,
               "mode": request.mode, "cutoff": request.cutoff.isoformat() if request.cutoff else None,
               "selected_span_ids": request.selected_span_ids, "status": "queued",
               "replicate": request.replicate, "created_at": datetime.now(UTC).isoformat(),
               "idempotency_key": idempotency_key, "cancel_requested": False}
        d.store.put("analyses", job["id"], job, document_id=request.document_id,
                    idempotency_key=idempotency_key)
        tasks.add_task(run_analysis, job["id"], d)
        return job

    @app.get("/analyses/{analysis_id}", dependencies=guard)
    def read_analysis(analysis_id: str, d: Deps = Depends(get_deps)):
        job = found(d.store.get("analyses", analysis_id), "analysis")
        manifest = d.store.get("manifests", analysis_id) or {}
        return {**job, "errors": manifest.get("errors", []),
                "rejections": manifest.get("rejections", [])}

    @app.get("/analyses/{analysis_id}/findings", dependencies=guard)
    def read_findings(analysis_id: str, d: Deps = Depends(get_deps)):
        found(d.store.get("analyses", analysis_id), "analysis")
        return d.store.find("findings", Finding, analysis_id=analysis_id)

    def trace(d: Deps, job: dict, finding: Finding) -> dict:
        """Everything the web application shows about one finding, in one record."""
        claim = d.store.get("claims", finding.claim_id, Claim)
        states = d.store.find("states", InvestigationState, claim_id=finding.claim_id)
        state = states[-1] if states else None
        document = d.store.get("documents", job["document_id"], DocumentSnapshot)
        spans = d.store.find("spans", SourceSpan, document_id=job["document_id"])
        heading = next((s.text for s in spans if s.kind == "heading"), None)
        manifest = d.store.get("manifests", job["id"]) or {}
        calls = manifest.get("calls", [])
        sources = {e.document_id: d.store.get("documents", e.document_id, DocumentSnapshot)
                   for e in (state.evidence if state else [])}
        return {
            "id": finding.finding_id, "analysis_id": job["id"], "claim_id": finding.claim_id,
            "claim": claim.text if claim else "", "status": finding.evidence_status,
            "mechanisms": finding.mechanisms, "review_status": finding.review_status,
            "stop_reason": finding.stop_reason, "partial": bool(job.get("partial")),
            # Jobs made before this field existed have no creation time of their own.
            "created_at": job.get("created_at") or (document.retrieved_at if document else None),
            "document": {"id": job["document_id"], "url": document.url if document else None,
                         "title": heading or (document.url if document else None) or "Pasted text"},
            "summary": finding.summary, "supported_rewrite": finding.supported_rewrite,
            "uncertainty": finding.uncertainty,
            # The share of checklist questions answered, weighted by materiality. Not a confidence.
            "coverage": coverage(state.questions) if state else 0.0,
            "questions": state.questions if state else [],
            "evidence": [{**e.model_dump(mode="json"),
                          "source_url": sources[e.document_id].url if sources.get(e.document_id) else None}
                         for e in (state.evidence if state else [])],
            "calculations": state.calculations if state else [],
            # Usage is recorded per analysis, so every finding of one document shows the same totals.
            "usage": {"models": manifest.get("models", {}), "updater": manifest.get("updater"),
                      "calls": calls,
                      "tokens": sum(c.get("input_tokens", 0) + c.get("output_tokens", 0) for c in calls),
                      "latency_ms": sum(c.get("latency_ms") or 0 for c in calls),
                      "replications": [c for c in calls if c.get("provider") == "devin"],
                      "errors": manifest.get("errors", [])}}

    @app.get("/traces", dependencies=guard)
    def list_traces(d: Deps = Depends(get_deps)):
        jobs = d.store.find("analyses")
        return [trace(d, job, finding) for job in jobs
                for finding in d.store.find("findings", Finding, analysis_id=job["id"])]

    @app.get("/traces/{finding_id}", dependencies=guard)
    def read_trace(finding_id: str, d: Deps = Depends(get_deps)):
        finding = found(d.store.get("findings", finding_id, Finding), "finding")
        job = next((j for j in d.store.find("analyses")
                    if d.store.find("findings", analysis_id=j["id"], claim_id=finding.claim_id)), None)
        return trace(d, found(job, "analysis"), finding)

    @app.get("/claims/{claim_id}", dependencies=guard)
    def read_claim(claim_id: str, d: Deps = Depends(get_deps)):
        claim = found(d.store.get("claims", claim_id, Claim), "claim")
        states = d.store.find("states", InvestigationState, claim_id=claim_id)
        latest = states[-1] if states else None
        return {"claim": claim, "questions": latest.questions if latest else [],
                "evidence": latest.evidence if latest else [],
                "withdrawn": latest.withdrawn if latest else [],
                "groups": latest.groups if latest else [],
                "coverage": coverage(latest.questions) if latest else 0.0,
                # Taken from the state, which drops a calculation when its inputs are withdrawn.
                "calculations": latest.calculations if latest else [],
                "stop_reason": latest.stop_reason if latest else None}

    @app.get("/evidence/{evidence_id}", dependencies=guard)
    def read_evidence(evidence_id: str, d: Deps = Depends(get_deps)):
        item = found(d.store.get("evidence", evidence_id, EvidenceItem), "evidence")
        return {"evidence": item, "span": d.store.get("spans", item.span_id, SourceSpan),
                "document": d.store.get("documents", item.document_id, DocumentSnapshot)}

    @app.get("/claims/{claim_id}/updates", dependencies=guard)
    def read_updates(claim_id: str, d: Deps = Depends(get_deps)):
        found(d.store.get("claims", claim_id), "claim")
        # Experimental scores are left out here. They are served by the research view only.
        internal = ("belief", "previous_score", "new_score")
        updates = sorted(d.store.find("updates", claim_id=claim_id), key=lambda u: u["version"])
        return [{k: v for k, v in u.items() if k not in internal} for u in updates]

    @app.get("/claims/{claim_id}/research", dependencies=guard)
    def read_research(claim_id: str, d: Deps = Depends(get_deps)):
        """Internal scores for one claim. Off unless COUNTERCHECK_RESEARCH_VIEW is set."""
        if not env("COUNTERCHECK_RESEARCH_VIEW"):
            raise HTTPException(404, "research view is not enabled")
        found(d.store.get("claims", claim_id), "claim")
        states = d.store.find("states", InvestigationState, claim_id=claim_id)
        latest = states[-1] if states else None
        updates = sorted(d.store.find("updates", BeliefUpdate, claim_id=claim_id),
                         key=lambda u: u.version)
        return {"notice": "Experimental and uncalibrated. Not a probability that the claim is "
                          "false, and not part of the finding.",
                "target": latest.target if latest else None,
                "belief": latest.belief if latest else None,
                "updates": [{"version": u.version, "strategy": u.strategy,
                             "input_state_hash": u.input_state_hash,
                             "previous_score": u.previous_score, "new_score": u.new_score,
                             "contributions": u.belief.contributions if u.belief else []}
                            for u in updates]}

    @app.post("/findings/{finding_id}/review", dependencies=guard)
    def review_finding(finding_id: str, request: ReviewRequest, d: Deps = Depends(get_deps)):
        finding = found(d.store.get("findings", finding_id, Finding), "finding")
        record = {"id": f"rv-{uuid.uuid4().hex[:12]}", "finding_id": finding_id,
                  "previous_status": finding.review_status, **request.model_dump()}
        # The review is stored as its own record, so the earlier state stays in the history.
        d.store.put("reviews", record["id"], record, finding_id=finding_id)
        finding.review_status = (ReviewState.blocked if request.decision == "reject"
                                 else ReviewState.human_reviewed)
        d.store.update("findings", finding_id, finding)
        return finding

    @app.post("/analyses/{analysis_id}/cancel", dependencies=guard)
    def cancel_analysis(analysis_id: str, d: Deps = Depends(get_deps)):
        job = found(d.store.get("analyses", analysis_id), "analysis")
        job["cancel_requested"] = True
        d.store.update("analyses", analysis_id, job)
        return job

    @app.get("/analyses/{analysis_id}/export", dependencies=guard)
    def export_analysis(analysis_id: str, d: Deps = Depends(get_deps)):
        job = found(d.store.get("analyses", analysis_id), "analysis")
        findings = d.store.find("findings", Finding, analysis_id=analysis_id)
        lines = [f"# Countercheck report for {job['document_id']}", ""]
        for f in findings:
            claim = d.store.get("claims", f.claim_id, Claim)
            lines += [f"## {claim.text if claim else f.claim_id}", f"Assessment: {f.evidence_status}",
                      f"Finding: {f.summary}", f"Supported wording: {f.supported_rewrite or 'none'}",
                      f"Unresolved: {'; '.join(f.uncertainty.critical_missing_questions) or 'none'}",
                      ""]
        return {"analysis": job, "findings": findings, "markdown": "\n".join(lines),
                "manifest": d.store.get("manifests", analysis_id)}

    return app


app = create_app()
