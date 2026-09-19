"""OpenAI adapter: structured calls through the Responses API, embeddings, and web search."""
from __future__ import annotations

import base64
import json

from openai import OpenAI
from pydantic import BaseModel

from backend.config import env
from backend.models import (
    Claim, InvestigationState, ProviderCall, RunManifest, SourceSpan, VerificationQuestion,
)
from backend.providers import prompts
from backend.providers.base import (
    ClaimDraft, ClaimDrafts, EvidenceAnalysis, ProviderError, QuestionDraft, QuestionDrafts,
    Report, ReviewResult, StateUpdate,
)


class OpenAILLM:
    def __init__(self, manifest: RunManifest | None = None) -> None:
        self.extract_model = env("OPENAI_EXTRACT_MODEL")
        self.reason_model = env("OPENAI_REASON_MODEL")
        self.embed_model = env("OPENAI_EMBED_MODEL")
        self.effort = env("OPENAI_REASONING_EFFORT")
        if not (env("OPENAI_API_KEY") and self.extract_model and self.reason_model):
            raise ProviderError(
                "OPENAI_API_KEY, OPENAI_EXTRACT_MODEL and OPENAI_REASON_MODEL must be set")
        self.client = OpenAI()
        self.manifest = manifest
        if manifest is not None:
            manifest.models.update(extract=self.extract_model, reason=self.reason_model,
                                   prompts=prompts.VERSION)

    def _parse(self, purpose: str, model: str, instructions: str, payload: dict,
               schema: type[BaseModel]):
        call = ProviderCall(provider="openai", purpose=purpose, model=model)
        try:
            response = self.client.responses.parse(
                model=model,
                input=[{"role": "developer", "content": instructions},
                       {"role": "user", "content": json.dumps(payload)}],
                text_format=schema,
                store=False,
                **({"reasoning": {"effort": self.effort}} if self.effort else {}),
            )
        except Exception as exc:
            call.error = str(exc)
            self._record(call)
            raise ProviderError(f"openai {purpose} failed: {exc}") from exc
        usage = response.usage
        if usage is not None:
            call.input_tokens = usage.input_tokens
            call.output_tokens = usage.output_tokens
            details = getattr(usage, "input_tokens_details", None)
            call.cached_tokens = getattr(details, "cached_tokens", 0) or 0
        self._record(call)
        if response.output_parsed is None:
            raise ProviderError(f"openai {purpose} returned no parsed output")
        return response.output_parsed

    def _record(self, call: ProviderCall) -> None:
        if self.manifest is not None:
            self.manifest.calls.append(call)

    def extract_claims(self, span: SourceSpan, context: list[SourceSpan]) -> list[ClaimDraft]:
        payload = {"passage": span.text, "context": [s.text for s in context]}
        return self._parse("extract", self.extract_model, prompts.EXTRACTOR, payload,
                           ClaimDrafts).claims

    def plan_questions(self, claim: Claim, checklist: list[str]) -> list[QuestionDraft]:
        payload = {"claim": claim.model_dump(mode="json"), "checklist": checklist}
        return self._parse("plan", self.reason_model, prompts.PLANNER, payload,
                           QuestionDrafts).questions

    def analyze_evidence(self, claim: Claim, questions: list[VerificationQuestion],
                         context: str) -> EvidenceAnalysis:
        payload = {"claim": claim.model_dump(mode="json"),
                   "questions": [{"id": q.id, "text": q.text} for q in questions],
                   "passages": context}
        return self._parse("analyze", self.reason_model, prompts.ANALYST, payload,
                           EvidenceAnalysis)

    def update_state(self, state: InvestigationState, new_evidence_ids: list[str]) -> StateUpdate:
        payload = {"state": state.model_dump(mode="json"), "new_evidence_ids": new_evidence_ids}
        return self._parse("update", self.reason_model, prompts.UPDATER, payload, StateUpdate)

    def review(self, state: InvestigationState, decisive: list[SourceSpan]) -> ReviewResult:
        payload = {"state": state.model_dump(mode="json"),
                   "original_passages": [{"id": s.id, "text": s.text} for s in decisive]}
        return self._parse("review", self.reason_model, prompts.REVIEWER, payload, ReviewResult)

    def report(self, state: InvestigationState, decisive: list[SourceSpan]) -> Report:
        payload = {"state": state.model_dump(mode="json"),
                   "original_passages": [{"id": s.id, "text": s.text} for s in decisive]}
        return self._parse("report", self.reason_model, prompts.REPORTER, payload, Report)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.embed_model:
            raise ProviderError("OPENAI_EMBED_MODEL is not set")
        try:
            response = self.client.embeddings.create(model=self.embed_model, input=texts)
        except Exception as exc:
            raise ProviderError(f"openai embed failed: {exc}") from exc
        self._record(ProviderCall(provider="openai", purpose="embed", model=self.embed_model,
                                  input_tokens=response.usage.total_tokens))
        return [item.embedding for item in response.data]

    def transcribe(self, png: bytes) -> str:
        """Read the text of one page image. Used for PDF pages that have no text layer."""
        picture = "data:image/png;base64," + base64.b64encode(png).decode()
        try:
            response = self.client.responses.create(
                model=self.extract_model, store=False,
                input=[{"role": "developer", "content": prompts.TRANSCRIBER},
                       {"role": "user", "content": [{"type": "input_image", "image_url": picture}]}])
        except Exception as exc:
            raise ProviderError(f"openai transcribe failed: {exc}") from exc
        usage = response.usage
        self._record(ProviderCall(provider="openai", purpose="transcribe", model=self.extract_model,
                                  input_tokens=usage.input_tokens if usage else 0,
                                  output_tokens=usage.output_tokens if usage else 0))
        return response.output_text

    def discover(self, query: str) -> list[str]:
        """Return candidate URLs only. The caller fetches and preserves each source."""
        try:
            response = self.client.responses.create(
                model=self.reason_model, tools=[{"type": "web_search"}],
                input=[{"role": "developer", "content": prompts.DISCOVERER},
                       {"role": "user", "content": json.dumps({"claim": query})}],
                include=["web_search_call.action.sources"], store=False,
            )
        except Exception as exc:
            raise ProviderError(f"openai discover failed: {exc}") from exc
        usage = response.usage
        self._record(ProviderCall(provider="openai", purpose="discover", model=self.reason_model,
                                  input_tokens=usage.input_tokens if usage else 0,
                                  output_tokens=usage.output_tokens if usage else 0))
        urls: list[str] = []
        for item in response.output:
            sources = getattr(getattr(item, "action", None), "sources", None) or []
            urls += [s.url for s in sources if getattr(s, "url", None)]
        return list(dict.fromkeys(urls))
