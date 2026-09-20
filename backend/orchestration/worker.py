"""Bounded analysis job: extract claims, investigate each in rounds, review, and store findings."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from backend.assessment.review import finalize, numbers_supported, run_review
from backend.belief.priority import choose, critical_open
from backend.belief import strategies
from backend.belief.state import apply_answers
from backend.claims.extract import extract, structure
from backend.compression.protect import build_context
from backend.config import Settings
from backend.db import Store
from backend.evidence.ledger import admissible
from backend.evidence.provenance import lineage, reconcile
from backend.ingestion.snapshot import admit
from backend.models import (
    AnswerStatus, Calculation, CalcInput, Claim, DocumentSnapshot, EvidenceItem, InvestigationState, Mode,
    ProviderCall, Relationship, RunManifest, ScoringTarget, SourceSpan, VerificationQuestion,
)
from backend.planning import checklists
from backend.planning.checklists import plan
from backend.providers import prompts
from backend.providers.base import LLM, Compressor, EvidenceAnalysis, ProviderError, Router
from backend.providers.devin import Session
from backend.replication.replicate import repositories
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
    # Runs the code of a linked repository in a Devin session to test claims about it. It takes
    # the repository address, the claim texts, an ACU limit, and a time limit. None when Devin is
    # not configured.
    replicator: Callable[[str, list[str], int, int], tuple[bytes | None, Session]] | None = None
    # What internal scores are scores of. An experiment on a labelled dataset declares its own.
    target: Callable[[Claim, datetime | None], ScoringTarget] = strategies.new_target
    # The decision protocol the planner and the updater are told. A dataset states its own; the
    # default is empty, and the prompts then state the protocol themselves.
    task: str = ""


def current_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=5).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _cancelled(store: Store, analysis_id: str) -> bool:
    return bool(store.get("analyses", analysis_id).get("cancel_requested"))


# Bases on which a claim that says nothing is a claim about the whole, so a passage about a part
# does measure something else. A claim about a total names no denominator, and a per-unit figure
# is therefore not comparable with it.
WHOLE_WHEN_UNSTATED = ("denominator", "population", "boundary")
# Passage kinds that carry the qualification a figure depends on: what a total excludes, which
# sites it covers, which period a column is. They are never put in compressible background.
QUALIFYING_KINDS = ("footnote", "table_row", "caption")


def _differences(differs_on: list[str], claim: Claim, span_id: str,
                 manifest: RunManifest) -> list[str]:
    """The bases on which the passage measures something other than the claim does.

    A difference of metric, unit or period only means something when the claim states that basis.
    A claim with no period cannot be measured over a different period, and counting that as a
    difference turns evidence about the claim into evidence about something else.
    """
    stated = {"metric": claim.metric, "unit": claim.unit, "denominator": claim.denominator,
              "population": claim.population, "boundary": claim.boundary, "period": claim.period}
    found = [f for f in differs_on if f in WHOLE_WHEN_UNSTATED or stated.get(f)]
    ignored = [f for f in differs_on if f not in found]
    if ignored:
        manifest.rejections.append(
            f"difference on {', '.join(ignored)} ignored for {span_id}: the claim states none")
    return found


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
        found = _differences(judgment.differs_on, claim, span.id, manifest)
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
            relationship=relationship, judged=judgment.relationship,
            target=judgment.target, comparable=not found,
            differences=found, origin=judgment.origin, limitations=limitations))
        if judgment.repeats_span_id:
            repeats[judgment.span_id] = judgment.repeats_span_id
    return items, repeats


def _calculations(analysis: EvidenceAnalysis, state: InvestigationState,
                  shown: dict[str, SourceSpan], manifest: RunManifest) -> list[Calculation]:
    results = []
    def key(inputs, steps, claim_output, claim_expected):
        # Two programs are the same calculation when they read the same numbers from the same
        # passages, combine them in the same order with the same operations, and put the same
        # result against the same stated value. Names chosen by the model are ignored; the order
        # of a step's arguments is not, because dividing a by b is not dividing b by a. A program
        # that tests the same arithmetic against a different stated value is a second reading of
        # the claim, not a repeat.
        identity = {i.name: f"{i.source_span_id}={i.value}" for i in inputs}
        position, wiring = {}, []
        for n, step in enumerate(steps):
            wiring.append((step.op, tuple(identity.get(a) or position.get(a) or f"?{a}"
                                          for a in step.args)))
            position[step.out] = f"#{n}"
        return (sorted(identity.values()), tuple(wiring),
                position.get(claim_output, claim_output), claim_expected)

    def stated(written):
        try:
            return parse_number(written) if written else None
        except CalculationError:
            return None

    done = [key(c.inputs, c.steps, c.claim_output, c.claim_expected) for c in state.calculations]
    for program in analysis.programs:
        calc_id = f"{state.claim.id}-n{len(state.calculations) + len(results)}"
        try:
            inputs = [CalcInput(**draft.model_dump(exclude={"value"}),
                                value=parse_number(draft.value)) for draft in program.inputs]
            for value in inputs:
                span = shown.get(value.source_span_id)
                if span is None or not value_in_source(value.value, span):
                    raise CalculationError(f"input {value.name} is not in its cited passage")
            here = key(inputs, program.steps, program.claim_output,
                       stated(program.claim_expected))
            if here in done:
                manifest.rejections.append(f"calculation {calc_id} repeats one already recorded")
                continue
            spans = [i.source_span_id for i in inputs]
            result = execute(calc_id, state.claim.id, inputs, program.steps, program.note,
                             lineage(state, spans))
            result.claim_output, result.round = program.claim_output, state.round + 1
            result.claim_expected, result.claim_relation = claim_relation(
                result.outputs, program.claim_output, program.claim_expected, state.claim.text)
            results.append(result)
            # Only a calculation that ran holds the key. A program that failed leaves the same
            # numbers free for a later program that gets the arithmetic right.
            done.append(here)
        except (CalculationError, ValueError) as exc:
            manifest.rejections.append(f"calculation rejected: {exc}")
    return results


def investigate(analysis_id: str, claim: Claim, deps: Deps, llm: LLM, manifest: RunManifest,
                mode: Mode, cutoff: datetime | None) -> tuple[InvestigationState, dict[str, SourceSpan]]:
    settings = deps.settings
    state = InvestigationState(claim=claim, task=deps.task,
                               questions=plan(claim, llm, manifest, deps.task),
                               target=deps.target(claim, cutoff))
    seen: dict[str, SourceSpan] = {}
    return _rounds(analysis_id, state, seen, settings.max_investigation_rounds, deps, llm,
                   manifest, mode, cutoff)


def _rounds(analysis_id: str, state: InvestigationState, seen: dict[str, SourceSpan], budget: int,
            deps: Deps, llm: LLM, manifest: RunManifest, mode: Mode, cutoff: datetime | None,
            requested: list[str] | None = None) -> tuple[InvestigationState, dict[str, SourceSpan]]:
    """Run up to `budget` rounds on the state. Used for the investigation and for follow-up.

    `requested` holds ids of questions that are searched for before any other open question.
    """
    store, settings, claim = deps.store, deps.settings, state.claim
    corpus = None
    if mode != Mode.live:
        documents = store.find("documents", DocumentSnapshot)
        corpus = [d.id for d in documents if admissible(d, mode, cutoff)]
    compressor = deps.compressor if settings.optimization.protected_compression else None
    tried: set[str] = set()  # queries discovery has already been asked, so none is repeated
    for _ in range(budget):
        if _cancelled(store, analysis_id):
            state.stop_reason = "cancelled"
            break
        first = [q for q in state.questions if q.id in (requested or [])
                 and q.status == AnswerStatus.open]
        selected = (first + [q for q in choose(state.questions) if q not in first])[:max(3, len(first))]
        if not selected:
            state.stop_reason = "no_open_questions"
            break
        passages, context = retrieve(deps.index, store, claim, selected, settings.retrieval,
                                     corpus, cutoff, manifest)
        # Look outside the document while a critical question is still open, or while nothing
        # was found at all. Where the passages came from does not say whether the questions are
        # answered, and one external passage that turned out to be irrelevant used to stop every
        # later round from looking. The query names the questions being worked on, and each
        # query is asked once per investigation so the search cannot repeat itself.
        query = " ".join([claim.text] + [q.text for q in selected])
        if mode == Mode.live and (not passages or critical_open(state.questions)) \
                and query not in tried:
            tried.add(query)
            if discover(llm, store, deps.index, query, manifest):
                passages, context = retrieve(deps.index, store, claim, selected,
                                             settings.retrieval, corpus, cutoff, manifest)
        if not passages:
            state.stop_reason = "no_source_in_allowed_corpus"
            break
        shown = {s.id: s for s in passages + context}
        seen.update(shown)
        # A footnote or a table row is where a document states what it excluded, so it is
        # protected with the passages that were retrieved. Only neighbouring narrative is left
        # compressible, and build_context checks nothing it puts in the background.
        notes = [s for s in context if s.kind in QUALIFYING_KINDS]
        prose = [s for s in context if s.kind not in QUALIFYING_KINDS]
        text, _ = build_context([f"[{s.id}] {s.text}" for s in passages + notes],
                                [f"[{s.id}] {s.text}" for s in prose], compressor, manifest)
        try:
            analysis = llm.analyze_evidence(claim, state.questions, text)
        except ProviderError as exc:
            manifest.errors.append(str(exc))
            state.stop_reason = "provider_error"
            break
        items, repeats = _items(analysis, state, shown, manifest, store)
        known = {e.id for e in state.evidence}
        reconcile(state, items, repeats)
        calculations = _calculations(analysis, state, shown, manifest)
        # Evidence, answers, and verified calculations are recorded before the updater runs, so
        # the updater is given the current round's results. They stay
        # recorded if the updater fails. Each calculation is appended here and nowhere else.
        state.calculations += calculations
        apply_answers(state, analysis.answers)
        state.round += 1
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
            # The updater has already decided on exactly this input, so the assessment stays.
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


def _store(store: Store, analysis_id: str, state: InvestigationState) -> None:
    """Write the state and its evidence rows. Called after each stage, so a job that stops early
    keeps the rows its stored updates refer to."""
    claim_id = state.claim.id
    for item in state.evidence:
        store.put("evidence", item.id, item, claim_id=claim_id, group_id=item.group_id,
                  span_id=item.span_id)
    for calculation in state.calculations:
        store.put("calculations", calculation.id, calculation, claim_id=claim_id)
    store.put("states", f"{analysis_id}-{claim_id}", state, analysis_id=analysis_id,
              claim_id=claim_id)


def _replicate(deps: Deps, claims: list[Claim], spans: list[SourceSpan], mode: Mode,
               manifest: RunManifest) -> None:
    """Run the code of each repository the document links to, and admit each report as a source.

    Nothing here changes an assessment. A report is a document that the investigation may cite,
    and a replication that gave no result is recorded as an error, not as evidence.
    """
    limits = deps.settings.replication
    if deps.replicator is None or mode != Mode.live:
        manifest.errors.append("replication was requested, but Devin is not configured or the "
                               "analysis is not in live mode")
        return
    found = repositories("\n".join(s.text for s in spans))[:limits.max_repositories]
    for repository in found:
        call = ProviderCall(provider="devin", purpose="replicate", billing_unit="acus")
        manifest.calls.append(call)
        try:
            content, session = deps.replicator(repository, [c.text for c in claims[:limits.max_claims]],
                                               limits.max_acu, limits.timeout_s)
        except ProviderError as exc:
            call.error = str(exc)
            manifest.errors.append(str(exc))
            continue
        call.acus, call.latency_ms = session.acus, int(session.seconds * 1000)
        if content is None:
            call.error = session.ended
            manifest.errors.append(f"replication of {repository} gave no result: {session.ended}")
            continue
        snapshot, report_spans = admit(deps.store, content, "text/html", url=session.url)
        deps.index.index(snapshot, report_spans)


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
        if job.get("claim_text"):
            # The claim was supplied, so it is read rather than searched for.
            claims = structure(job["claim_text"], spans, llm, manifest, f"{analysis_id}-")
        else:
            claims = extract(spans, llm, router, manifest, set(job.get("selected_span_ids") or []),
                             id_prefix=f"{analysis_id}-")
        if job.get("replicate") and claims:
            # Asked for by this analysis only. The report is in the corpus before any claim is
            # investigated, so every claim can cite it.
            _replicate(deps, claims, spans, mode, manifest)
        save("running", claims_total=len(claims), claims_done=0)
        for done, claim in enumerate(claims, start=1):
            if _cancelled(store, analysis_id):
                # Work already stored stays, and the job is not reported as complete.
                save("cancelled", partial=True)
                return
            store.put("claims", claim.id, claim, analysis_id=analysis_id,
                      document_id=claim.document_id)
            state, seen = investigate(analysis_id, claim, deps, llm, manifest, mode, cutoff)
            _store(store, analysis_id, state)
            if state.stop_reason == "cancelled":
                save("cancelled", partial=True)
                return
            review = run_review(state, seen, llm, manifest)
            # A reason with a number found in no source is not turned into a question.
            checks = [r for r in review.reasons if numbers_supported(r, state, seen)] \
                if review and review.decision == "request_check" else []
            if checks and settings.max_follow_up_rounds:
                # Each requested check becomes a critical question that is searched for first.
                asked = [VerificationQuestion(
                    id=f"{claim.id}-r{i}", claim_id=claim.id, text=reason, materiality=3,
                    critical=True, why_it_matters="requested by review")
                    for i, reason in enumerate(checks)]
                state.questions += asked
                state, seen = _rounds(analysis_id, state, seen, settings.max_follow_up_rounds,
                                      deps, llm, manifest, mode, cutoff, [q.id for q in asked])
                _store(store, analysis_id, state)
                if state.stop_reason == "cancelled":
                    save("cancelled", partial=True)
                    return
                review = run_review(state, seen, llm, manifest)
            finding = finalize(state, seen, llm, review, cutoff, manifest)
            _store(store, analysis_id, state)
            store.put("findings", finding.finding_id, finding, analysis_id=analysis_id,
                      claim_id=claim.id)
            save("running", claims_done=done)
        # Operational errors mean some work did not run, so the result is labelled partial.
        save("complete", partial=bool(manifest.errors))
    except Exception as exc:  # store status 'failed' so the job is not reported as complete
        manifest.errors.append(f"analysis failed: {exc!r}")
        save("failed", partial=True)
