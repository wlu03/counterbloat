"""Bounded analysis job: extract claims, investigate each in rounds, review, and store findings."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from backend.assessment.review import finalize
from backend.belief.priority import choose, critical_open
from backend.belief.state import apply_answers, apply_update
from backend.claims.extract import extract
from backend.compression.protect import build_context
from backend.config import Settings
from backend.db import Store
from backend.evidence.ledger import admissible
from backend.evidence.provenance import lineage, reconcile
from backend.models import (
    Calculation, CalcInput, Claim, DocumentSnapshot, EvidenceItem, InvestigationState, Mode,
    Relationship, RunManifest, SourceSpan,
)
from backend.planning.checklists import plan
from backend.providers import prompts
from backend.providers.base import LLM, Compressor, EvidenceAnalysis, ProviderError, Router
from backend.retrieval.discovery import discover
from backend.retrieval.search import SearchIndex, retrieve
from backend.verification.comparability import FIELDS, differences
from backend.verification.numeric import CalculationError, execute, parse_number, value_in_source


@dataclass
class Deps:
    store: Store
    index: SearchIndex
    settings: Settings
    llm_factory: Callable[[RunManifest], LLM]
    router: Router | None = None
    compressor: Compressor | None = None


def _cancelled(store: Store, analysis_id: str) -> bool:
    return bool(store.get("analyses", analysis_id).get("cancel_requested"))


def _items(analysis: EvidenceAnalysis, state: InvestigationState, shown: dict[str, SourceSpan],
           manifest: RunManifest) -> tuple[list[EvidenceItem], dict[str, str]]:
    claim = state.claim
    claim_fields = claim.model_dump(include=set(FIELDS))
    items, repeats = [], {}
    for judgment in analysis.judgments:
        span = shown.get(judgment.span_id)
        if span is None or judgment.quote not in span.text:
            manifest.errors.append(f"rejected evidence with unverifiable quote: {judgment.span_id}")
            continue
        found = differences(claim_fields, judgment.model_dump(include=set(FIELDS)))
        relationship, limitations = judgment.relationship, list(judgment.limitations)
        if found and relationship == Relationship.contradicts:
            # Evidence measured on another basis qualifies the claim. It does not contradict it.
            relationship = Relationship.qualifies
            limitations.append("not directly comparable: " + ", ".join(found))
        items.append(EvidenceItem(
            id=f"{claim.id}-e{len(state.evidence) + len(items)}", claim_id=claim.id,
            span_id=span.id, document_id=span.document_id, quote=judgment.quote,
            relationship=relationship, target=judgment.target, comparable=not found,
            differences=found, origin=judgment.origin, limitations=limitations))
        if judgment.repeats_span_id:
            repeats[judgment.span_id] = judgment.repeats_span_id
    return items, repeats


def _calculations(analysis: EvidenceAnalysis, state: InvestigationState,
                  shown: dict[str, SourceSpan], manifest: RunManifest) -> list[Calculation]:
    results = []
    done = [(c.inputs, c.steps) for c in state.calculations]
    for program in analysis.programs:
        calc_id = f"{state.claim.id}-n{len(state.calculations) + len(results)}"
        try:
            inputs = [CalcInput(**draft.model_dump(exclude={"value"}),
                                value=parse_number(draft.value)) for draft in program.inputs]
            for value in inputs:
                span = shown.get(value.source_span_id)
                if span is None or not value_in_source(value.value, span):
                    raise CalculationError(f"input {value.name} is not in its cited passage")
            if (inputs, program.steps) in done:
                continue  # the same calculation was already recorded in an earlier round
            spans = [i.source_span_id for i in inputs]
            results.append(execute(calc_id, state.claim.id, inputs, program.steps, program.note,
                                   lineage(state, spans)))
        except (CalculationError, ValueError) as exc:
            manifest.errors.append(f"calculation rejected: {exc}")
    return results


def investigate(analysis_id: str, claim: Claim, deps: Deps, llm: LLM, manifest: RunManifest,
                mode: Mode, cutoff: datetime | None) -> tuple[InvestigationState, dict[str, SourceSpan]]:
    store, settings = deps.store, deps.settings
    state = InvestigationState(claim=claim, questions=plan(claim, llm))
    seen: dict[str, SourceSpan] = {}
    corpus = None
    if mode != Mode.live:
        documents = store.find("documents", DocumentSnapshot)
        corpus = [d.id for d in documents if admissible(d, mode, cutoff)]
    compressor = deps.compressor if settings.optimization.protected_compression else None
    for _ in range(settings.max_investigation_rounds):
        if _cancelled(store, analysis_id):
            state.stop_reason = "cancelled"
            break
        selected = choose(state.questions)
        if not selected:
            state.stop_reason = "no_open_questions"
            break
        passages, context = retrieve(deps.index, store, claim, selected, settings.retrieval,
                                     corpus, cutoff)
        if mode == Mode.live and all(p.document_id == claim.document_id for p in passages):
            if discover(llm, store, deps.index, claim.text, mode, manifest):
                passages, context = retrieve(deps.index, store, claim, selected,
                                             settings.retrieval, corpus, cutoff)
        if not passages:
            state.stop_reason = "no_source_in_allowed_corpus"
            break
        shown = {s.id: s for s in passages + context}
        seen.update(shown)
        text, _ = build_context([f"[{s.id}] {s.text}" for s in passages],
                                [f"[{s.id}] {s.text}" for s in context], compressor, manifest)
        try:
            analysis = llm.analyze_evidence(claim, state.questions, text)
        except ProviderError as exc:
            manifest.errors.append(str(exc))
            state.stop_reason = "provider_error"
            break
        items, repeats = _items(analysis, state, shown, manifest)
        known = {e.id for e in state.evidence}
        changed = reconcile(state, items, repeats)
        calculations = _calculations(analysis, state, shown, manifest)
        apply_answers(state, analysis.answers)
        state.round += 1
        if not changed and not calculations:
            # Nothing new was admitted, so the assessment is left as it was.
            state.stop_reason = "no_new_evidence"
            break
        new_ids = [e.id for e in state.evidence if e.id not in known]
        try:
            update = llm.update_state(state, new_ids)
        except ProviderError as exc:
            manifest.errors.append(str(exc))
            state.stop_reason = "provider_error"
            break
        record = apply_update(state, update, new_ids, calculations, prompts.VERSION)
        store.put("updates", record.id, record, claim_id=claim.id)
        store.put("states", f"{analysis_id}-{claim.id}", state, analysis_id=analysis_id,
                  claim_id=claim.id)
        if not critical_open(state.questions) and not choose(state.questions):
            state.stop_reason = "resolved"
            break
    else:
        state.stop_reason = "budget_exhausted"
    return state, seen


def run_analysis(analysis_id: str, deps: Deps) -> None:
    store = deps.store
    job = store.get("analyses", analysis_id)
    mode = Mode(job.get("mode") or deps.settings.mode)
    cutoff = datetime.fromisoformat(job["cutoff"]) if job.get("cutoff") else None
    manifest = RunManifest(analysis_id=analysis_id, mode=mode, cutoff=cutoff,
                           config_hash=deps.settings.config_hash())

    def save(status: str, **extra) -> None:
        current = store.get("analyses", analysis_id)
        current.update(status=status, **extra)
        store.update("analyses", analysis_id, current)
        store.put("manifests", analysis_id, manifest, analysis_id=analysis_id)

    try:
        llm = deps.llm_factory(manifest)
        spans = store.find("spans", SourceSpan, document_id=job["document_id"])
        router = deps.router if deps.settings.optimization.jev_routing else None
        claims = extract(spans, llm, router, manifest, set(job.get("selected_span_ids") or []),
                         id_prefix=f"{analysis_id}-")
        save("running", claims_total=len(claims), claims_done=0)
        for done, claim in enumerate(claims, start=1):
            if _cancelled(store, analysis_id):
                # Work already stored stays, and the job is not reported as complete.
                save("cancelled", partial=True)
                return
            store.put("claims", claim.id, claim, analysis_id=analysis_id,
                      document_id=claim.document_id)
            state, seen = investigate(analysis_id, claim, deps, llm, manifest, mode, cutoff)
            store.put("states", f"{analysis_id}-{claim.id}", state, analysis_id=analysis_id,
                      claim_id=claim.id)
            for item in state.evidence:
                store.put("evidence", item.id, item, claim_id=claim.id, group_id=item.group_id,
                          span_id=item.span_id)
            for calculation in state.calculations:
                store.put("calculations", calculation.id, calculation, claim_id=claim.id)
            finding = finalize(state, seen, llm, cutoff)
            store.put("findings", finding.finding_id, finding, analysis_id=analysis_id,
                      claim_id=claim.id)
            save("running", claims_done=done)
        save("complete", partial=False)
    except Exception as exc:  # a failed job must say so instead of looking finished
        manifest.errors.append(f"analysis failed: {exc}")
        save("failed", partial=True)
