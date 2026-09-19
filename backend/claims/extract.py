"""Route passages, extract claims, and keep only claims whose quote exists in the source."""
from __future__ import annotations

import re

from backend.models import Claim, RunManifest, SourceSpan
from backend.providers.base import LLM, ClaimDraft, ProviderError, Router

# Jev may exclude a passage only when it is this sure the passage makes no assertion.
EXCLUDE_CONFIDENCE = 0.8
CANDIDATE_KINDS = ("paragraph", "heading", "caption")


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "").rstrip(".") for n in re.findall(r"\d[\d,]*\.?\d*", text)}


def valid(draft: ClaimDraft, span: SourceSpan) -> bool:
    """The quote must be verbatim, and every number in a stated value must be a number in it."""
    if not draft.quote or draft.quote not in span.text:
        return False
    if draft.value and not _numbers(draft.value) <= _numbers(draft.quote):
        return False
    return True


def extract(spans: list[SourceSpan], llm: LLM, router: Router | None, manifest: RunManifest,
            selected_span_ids: set[str] | None = None, id_prefix: str = "") -> list[Claim]:
    selected = selected_span_ids or set()
    by_id = {s.id: s for s in spans}
    claims: list[Claim] = []
    for span in spans:
        if span.kind not in CANDIDATE_KINDS:
            continue
        if router is not None and span.id not in selected:
            try:
                route = router.route(span.text)
                if not route.is_claim and route.confidence >= EXCLUDE_CONFIDENCE:
                    continue
            except ProviderError as exc:
                manifest.errors.append(str(exc))  # routing failed, so extract from the passage
        context = [by_id[i] for i in (span.prev_id, span.next_id, *span.note_ids) if i in by_id]
        try:
            drafts = llm.extract_claims(span, context)
        except ProviderError as exc:
            manifest.errors.append(str(exc))
            continue
        for draft in drafts:
            if not valid(draft, span):
                manifest.errors.append(f"rejected claim with unverifiable quote in {span.id}")
                continue
            start = span.start + span.text.index(draft.quote)
            claims.append(Claim(
                id=f"{id_prefix}{span.id}-c{len(claims)}", document_id=span.document_id, span_id=span.id,
                text=draft.quote, start=start, end=start + len(draft.quote),
                **draft.model_dump(exclude={"quote"})))
    return claims
