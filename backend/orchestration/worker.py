"""Bounded analysis job: extract claims, investigate each in rounds, review, and store findings."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from backend.assessment.review import finalize, run_review
from backend.belief.priority import choose, critical_open
from backend.belief import strategies
from backend.belief.state import apply_answers
from backend.claims.extract import extract
from backend.compression.protect import build_context
from backend.config import Settings
from backend.db import Store
from backend.evidence.ledger import admissible
from backend.evidence.provenance import lineage, reconcile
from backend.models import (
    Calculation, CalcInput, Claim, DocumentSnapshot, EvidenceItem, InvestigationState, Mode,
    Relationship, RunManifest, ScoringTarget, SourceSpan, VerificationQuestion,
)
from backend.planning import checklists
from backend.planning.checklists import plan
from backend.providers import prompts
from backend.providers.base import LLM, Compressor, EvidenceAnalysis, ProviderError, Router
from backend.retrieval.discovery import discover
from backend.retrieval.search import SearchIndex, retrieve
from backend.verification.numeric import (
    CalculationError, claim_relation, execute, parse_number, value_in_source,
)


@dataclass
class Deps:
    store: Store
    index: SearchIndex
    settings: Settings
    llm_factory: Callable[[RunManifest], LLM]
    router: Router | None = None
    compressor: Compressor | None = None
    transcribe: Callable[[bytes], str] | None = None  # reads PDF pages that have no text layer
    # What internal scores are scores of. An experiment on a labelled dataset declares its own.
    target: Callable[[Claim, datetime | None], ScoringTarget] = strategies.new_target


def current_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _cancelled(store: Store, analysis_id: str) -> bool:
    return bool(store.get("analyses", analysis_id).get("cancel_requested"))


def _items(analysis: EvidenceAnalysis, state: InvestigationState, shown: dict[str, SourceSpan],
           manifest: RunManifest, store: Store) -> tuple[list[EvidenceItem], dict[str, str]]:
    claim = state.claim
    items, repeats = [], {}
    known = {(e.span_id, e.target) for e in state.evidence}
    for judgment in analysis.judgments:
        span = shown.get(judgment.span_id)
        if span is None or not judgment.quote.strip() or judgment.quote not in span.text:
            manifest.rejections.append(f"evidence quote not found in passage {judgment.span_id}")
            continue
        if span.id == claim.span_id and (judgment.quote in claim.text or claim.text in judgment.quote):
            continue  # the claim's own sentence is not evidence for the claim
        if (span.id, judgment.target) in known:
            continue  # already recorded, so every item built here is new and ids stay unique
        known.add((span.id, judgment.target))
        found = list(judgment.differs_on)
        relationship, limitations = judgment.relationship, list(judgment.limitations)
        if found and relationship == Relationship.contradicts:
            # Evidence measured on another basis qualifies the claim. It does not contradict it.
            relationship = Relationship.qualifies
            limitations.append("not directly comparable: " + ", ".join(found))
        source = store.get("documents", span.document_id, DocumentSnapshot)
        items.append(EvidenceItem(
            id=f"{claim.id}-e{len(state.evidence) + len(items)}", claim_id=claim.id,
            span_id=span.id, document_id=span.document_id, quote=judgment.quote,
            document_sha256=source.sha256 if source else None,
            published_at=source.published_at if source else None, round=state.round + 1,
            start=span.start, end=span.end,
            relationship=relationship, target=judgment.target, comparable=not found,
            differences=found, origin=judgment.origin, limitations=limitations))
        if judgment.repeats_span_id:
            repeats[judgment.span_id] = judgment.repeats_span_id
    return items, repeats


def _calculations(analysis: EvidenceAnalysis, state: InvestigationState,
                  shown: dict[str, SourceSpan], manifest: RunManifest) -> list[Calculation]:
    results = []
    def key(inputs, steps):
        # Two programs are the same calculation when they read the same numbers from the same
        # passages and apply the same operations. Names chosen by the model are ignored.
        return (sorted((i.source_span_id, i.value) for i in inputs), [s.op for s in steps])

    done = [key(c.inputs, c.steps) for c in state.calculations]
    for program in analysis.programs:
        calc_id = f"{state.claim.id}-n{len(state.calculations) + len(results)}"
        try:
            inputs = [CalcInput(**draft.model_dump(exclude={"value"}),
                                value=parse_number(draft.value)) for draft in program.inputs]
            for value in inputs:
                span = shown.get(value.source_span_id)
                if span is None or not value_in_source(value.value, span):
                    raise CalculationError(f"input {value.name} is not in its cited passage")
            if key(inputs, program.steps) in done:
                continue  # the same calculation was already recorded
            done.append(key(inputs, program.steps))
            spans = [i.source_span_id for i in inputs]
            result = execute(calc_id, state.claim.id, inputs, program.steps, program.note,
                             lineage(state, spans))
            result.claim_output, result.round = program.claim_output, state.round + 1
            result.claim_expected, result.claim_relation = claim_relation(
                result.outputs, program.claim_output, program.claim_expected, state.claim.text)
            results.append(result)
        except (CalculationError, ValueError) as exc:
            manifest.rejections.append(f"calculation rejected: {exc}")
    return results


def investigate(analysis_id: str, claim: Claim, deps: Deps, llm: LLM, manifest: RunManifest,
                mode: Mode, cutoff: datetime | None) -> tuple[InvestigationState, dict[str, SourceSpan]]:
    settings = deps.settings
    state = InvestigationState(claim=claim, questions=plan(claim, llm, manifest),
                               target=deps.target(claim, cutoff))
    seen: dict[str, SourceSpan] = {}
    return _rounds(analysis_id, state, seen, settings.max_investigation_rounds, deps, llm,
                   manifest, mode, cutoff)


def _rounds(analysis_id: str, state: InvestigationState, seen: dict[str, SourceSpan], budget: int,
            deps: Deps, llm: LLM, manifest: RunManifest, mode: Mode,
            cutoff: datetime | None) -> tuple[InvestigationState, dict[str, SourceSpan]]:
    """Run up to `budget` rounds on the state. Used for the investigation and for follow-up."""
    store, settings, claim = deps.store, deps.settings, state.claim
    corpus = None
    if mode != Mode.live:
        documents = store.find("documents", DocumentSnapshot)
        corpus = [d.id for d in documents if admissible(d, mode, cutoff)]
    compressor = deps.compressor if settings.optimization.protected_compression else None
    for _ in range(budget):
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
            if discover(llm, store, deps.index, claim.text, manifest):
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
        items, repeats = _items(analysis, state, shown, manifest, store)
        known = {e.id for e in state.evidence}
        changed = reconcile(state, items, repeats)
        calculations = _calculations(analysis, state, shown, manifest)
        # Evidence, answers, and verified calculations are recorded before the updater runs, so
        # the updater decides with the current round's results in front of it. They stay
        # recorded if the updater fails. Each calculation is appended here and nowhere else.
        state.calculations += calculations
        apply_answers(state, analysis.answers)
        state.round += 1
        if not changed and not calculations:
            # Nothing new was admitted, so the assessment is left as it was.
            state.stop_reason = "no_new_evidence"
            break
        new_ids = [e.id for e in state.evidence if e.id not in known]
        try:
            record = strategies.step(state, new_ids, [c.id for c in calculations], llm,
                                     settings.assessment, manifest, prompts.VERSION)
        except ProviderError as exc:
            # The observations above stay recorded. No assessment transition is recorded.
            manifest.errors.append(str(exc))
            state.stop_reason = "provider_error"
            break
        if record is None:
            state.stop_reason = "no_new_evidence"
            break
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
                           config_hash=deps.settings.config_hash(), commit=current_commit(),
                           updater=deps.settings.assessment.updater)

    def save(status: str, **extra) -> None:
        current = store.get("analyses", analysis_id)
        current.update(status=status, **extra)
        store.update("analyses", analysis_id, current)
        store.put("manifests", analysis_id, manifest, analysis_id=analysis_id)

    settings = deps.settings
    try:
        llm = deps.llm_factory(manifest)
        manifest.models["checklists"] = checklists.VERSION
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
            if state.stop_reason == "cancelled":
                save("cancelled", partial=True)
                return
            review = run_review(state, seen, llm, manifest)
            if review and review.decision == "request_check" and settings.max_follow_up_rounds:
                # The requested check becomes a critical question and gets its own bounded rounds.
                state.questions += [VerificationQuestion(
                    id=f"{claim.id}-r{i}", claim_id=claim.id, text=reason, materiality=3,
                    critical=True, why_it_matters="requested by review")
                    for i, reason in enumerate(review.reasons)]
                state, seen = _rounds(analysis_id, state, seen, settings.max_follow_up_rounds,
                                      deps, llm, manifest, mode, cutoff)
                store.put("states", f"{analysis_id}-{claim.id}", state, analysis_id=analysis_id,
                          claim_id=claim.id)
                review = run_review(state, seen, llm, manifest)
            finding = finalize(state, seen, llm, review, cutoff, manifest)
            for item in state.evidence:
                store.put("evidence", item.id, item, claim_id=claim.id, group_id=item.group_id,
                          span_id=item.span_id)
            for calculation in state.calculations:
                store.put("calculations", calculation.id, calculation, claim_id=claim.id)
            store.put("states", f"{analysis_id}-{claim.id}", state, analysis_id=analysis_id,
                      claim_id=claim.id)
            store.put("findings", finding.finding_id, finding, analysis_id=analysis_id,
                      claim_id=claim.id)
            manifest.embedding_search = getattr(deps.index, "used_embeddings", None)
            save("running", claims_done=done)
        # Operational errors mean some work did not run, so the result is labelled partial.
        save("complete", partial=bool(manifest.errors))
    except Exception as exc:  # store status 'failed' so the job is not reported as complete
        manifest.errors.append(f"analysis failed: {exc!r}")
        save("failed", partial=True)
