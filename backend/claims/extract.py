"""Route passages, extract claims, and keep only claims whose quote exists in the source."""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from backend.models import Claim, ProviderCall, RunManifest, SourceSpan
from backend.providers.base import LLM, ClaimDraft, ProviderError, Router

# Jev may exclude a passage only when it is this sure the passage makes no assertion.
EXCLUDE_CONFIDENCE = 0.8
CANDIDATE_KINDS = ("paragraph", "heading", "caption")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", text)}


def valid(draft: ClaimDraft, span: SourceSpan) -> bool:
    """The quote must be verbatim, and every number in a stated value must be a number in it."""
    if not draft.quote.strip() or draft.quote not in span.text:
        return False
    if draft.value and not _numbers(draft.value) <= _numbers(draft.quote):
        return False
    return True


def _build(draft: ClaimDraft, span: SourceSpan, claim_id: str) -> Claim:
    start = span.start + span.text.index(draft.quote)
    return Claim(id=claim_id, document_id=span.document_id, span_id=span.id, text=draft.quote,
                 start=start, end=start + len(draft.quote), **draft.model_dump(exclude={"quote"}))


def structure(text: str, spans: list[SourceSpan], llm: LLM, manifest: RunManifest,
              id_prefix: str = "") -> list[Claim]:
    """Read the structured fields of a claim the caller supplied, rather than deciding whether the
    document makes one.

    The claim must be a verbatim quote of one passage, so the finding can point at where it is
    written. The extractor's job is to find claims worth checking in a document, and it declines
    a general statement of fact. A claim a person or a dataset handed over has already been chosen.
    """
    span = next((s for s in spans if text in s.text), None)
    if span is None:
        manifest.rejections.append("the supplied claim is not a verbatim quote of any passage")
        return []
    try:
        draft = llm.structure_claim(text, span)
    except ProviderError as exc:
        manifest.errors.append(str(exc))
        return []
    # The model may only read the fields of the supplied wording, so its quote is that wording.
    draft.quote = text
    if not valid(draft, span):
        manifest.rejections.append("the structured fields of the supplied claim state a number "
                                   "that its wording does not")
        return []
    return [_build(draft, span, f"{id_prefix}{span.id}-c0")]


@dataclass
class _Result:
    """What reading one passage produced, kept apart so workers share no state."""
    claims: list[Claim] = field(default_factory=list)
    calls: list[ProviderCall] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    skipped: int = 0


def _read_span(span: SourceSpan, by_id: dict[str, SourceSpan], llm: LLM, router: Router | None,
               selected: set[str], id_prefix: str) -> _Result:
    out = _Result()
    if router is not None and span.id not in selected:
        started = time.monotonic()
        call = ProviderCall(provider="jev", purpose="route", billing_unit="requests")
        out.calls.append(call)
        try:
            route = router.route(span.text)
            call.latency_ms = int((time.monotonic() - started) * 1000)
            if not route.is_claim and route.confidence >= EXCLUDE_CONFIDENCE:
                out.skipped += 1
                return out
        except ProviderError as exc:
            call.error = str(exc)
            out.errors.append(str(exc))  # routing failed, so extract from the passage
    context = [by_id[i] for i in (span.prev_id, span.next_id, *span.note_ids) if i in by_id]
    try:
        drafts = llm.extract_claims(span, context)
    except ProviderError as exc:
        out.errors.append(str(exc))
        return out
    seen: set[str] = set()
    for draft in drafts:
        if not valid(draft, span):
            out.rejections.append(f"claim quote not found in passage {span.id}")
            continue
        if draft.quote in seen:
            continue  # The same wording returned twice is one claim, not two.
        seen.add(draft.quote)
        # Numbered within its own passage, so the id does not depend on the order in which
        # passages happened to finish.
        out.claims.append(_build(draft, span, f"{id_prefix}{span.id}-c{len(out.claims)}"))
    return out


def extract(spans: list[SourceSpan], llm: LLM, router: Router | None, manifest: RunManifest,
            selected_span_ids: set[str] | None = None, id_prefix: str = "",
            workers: int = 1) -> list[Claim]:
    """Read every candidate passage and return the claims found, in passage order.

    Each passage is read on its own, so `workers` above one reads several at a time. The waiting
    is on the provider, not on this process. Results are merged in passage order, so the claims,
    their identifiers and the run manifest come out the same whatever the worker count.
    """
    selected = selected_span_ids or set()
    by_id = {s.id: s for s in spans}
    candidates = [s for s in spans if s.kind in CANDIDATE_KINDS]
    if workers > 1 and len(candidates) > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(
                lambda span: _read_span(span, by_id, llm, router, selected, id_prefix),
                candidates))
    else:
        results = [_read_span(s, by_id, llm, router, selected, id_prefix) for s in candidates]
    claims: list[Claim] = []
    for result in results:
        claims += result.claims
        manifest.calls += result.calls
        manifest.errors += result.errors
        manifest.rejections += result.rejections
        manifest.skipped_by_router += result.skipped
    return claims
