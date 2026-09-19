"""HTTP API (specification section 13.3). Every endpoint defined here requires the application key."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from backend.belief.priority import coverage
from backend.config import env, load_settings
from backend.db import Store
from backend.ingestion.fetch import BlockedDestination, FetchError
from backend.ingestion.snapshot import admit, admit_url, normalized_text
from backend.models import (
    Calculation, Claim, DocumentSnapshot, EvidenceItem, Finding, InvestigationState, Mode,
    ReviewState, SourceSpan,
)
from backend.orchestration.worker import Deps, run_analysis
from backend.providers.base import ProviderError
from backend.retrieval.memory import MemoryIndex


class DocumentRequest(BaseModel):
    url: str | None = None
    content: str | None = None
    media_type: str = "text/html"
    published_at: datetime | None = None


class AnalysisRequest(BaseModel):
    document_id: str
    mode: Mode | None = None
    cutoff: datetime | None = None
    selected_span_ids: list[str] = []


class ReviewRequest(BaseModel):
    reviewer: str
    decision: str
    note: str = ""


def default_deps() -> Deps:
    from backend.providers.openai_client import OpenAILLM

    settings = load_settings()
    store = Store(env("DATABASE_URL", "sqlite:///countercheck.db"))
    if env("ELASTICSEARCH_URL"):
        from backend.retrieval.elastic import ElasticIndex
        try:
            index = ElasticIndex(OpenAILLM())
        except ProviderError:
            index = ElasticIndex()
    else:
        index = MemoryIndex()
    router = compressor = None
    if env("TYPESAFE_API_KEY"):
        from backend.providers.jev import JevRouter
        router = JevRouter()
    if env("TTC_API_KEY"):
        from backend.providers.ttc import TokenCompanyCompressor
        compressor = TokenCompanyCompressor()
    return Deps(store=store, index=index, settings=settings, llm_factory=OpenAILLM,
                router=router, compressor=compressor)


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
                snapshot, spans = admit_url(d.store, request.url, published_at=request.published_at)
            elif request.content:
                snapshot, spans = admit(d.store, request.content.encode(), request.media_type,
                                        published_at=request.published_at)
            else:
                raise HTTPException(422, "provide url or content")
        except (FetchError, BlockedDestination) as exc:
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
                return existing[0]
        job = {"id": f"an-{uuid.uuid4().hex[:12]}", "document_id": request.document_id,
               "mode": request.mode, "cutoff": request.cutoff.isoformat() if request.cutoff else None,
               "selected_span_ids": request.selected_span_ids, "status": "queued",
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

    @app.get("/claims/{claim_id}", dependencies=guard)
    def read_claim(claim_id: str, d: Deps = Depends(get_deps)):
        claim = found(d.store.get("claims", claim_id, Claim), "claim")
        states = d.store.find("states", InvestigationState, claim_id=claim_id)
        latest = states[-1] if states else None
        return {"claim": claim, "questions": latest.questions if latest else [],
                "evidence": latest.evidence if latest else [],
                "coverage": coverage(latest.questions) if latest else 0.0,
                "calculations": d.store.find("calculations", Calculation, claim_id=claim_id),
                "stop_reason": latest.stop_reason if latest else None}

    @app.get("/evidence/{evidence_id}", dependencies=guard)
    def read_evidence(evidence_id: str, d: Deps = Depends(get_deps)):
        item = found(d.store.get("evidence", evidence_id, EvidenceItem), "evidence")
        return {"evidence": item, "span": d.store.get("spans", item.span_id, SourceSpan),
                "document": d.store.get("documents", item.document_id, DocumentSnapshot)}

    @app.get("/claims/{claim_id}/updates", dependencies=guard)
    def read_updates(claim_id: str, d: Deps = Depends(get_deps)):
        return sorted(d.store.find("updates", claim_id=claim_id), key=lambda u: u["version"])

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
