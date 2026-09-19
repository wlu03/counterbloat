"""Versioned verification checklists per claim family (specification section 6.5)."""
from __future__ import annotations

import re

from backend.models import AssertionType, Claim, VerificationQuestion
from backend.providers.base import LLM, ProviderError

VERSION = "checklists-v1"

CHECKLISTS: dict[str, list[str]] = {
    "environmental": [
        "Is the stated change absolute or intensity-based?",
        "Which baseline period and value does the comparison use?",
        "Do both periods cover the same operations and reporting method?",
        "Which emissions or lifecycle components are included?",
    ],
    "business_growth": [
        "Is the growth organic or acquisition-driven?",
        "Are the compared periods comparable?",
        "Which metric is measured: revenue, bookings, users, or another?",
        "Do one-off contributions affect the figure?",
    ],
    "ai_capability": [
        "Which task and metric does the capability refer to?",
        "What population was it evaluated on, and was the data held out?",
        "How much human assistance is involved?",
        "What deployment restrictions apply?",
    ],
    "product_attribute": [
        "Which components does the attribute cover?",
        "Under which conditions does it hold, and what is excluded?",
        "Which test or certification covers the claim?",
    ],
    "privacy_security": [
        "Which data, processing, and threat model does the statement cover?",
        "What exceptions apply?",
        "Is this a stated policy or a verified implementation?",
    ],
    "future_target": [
        "Which metric, boundary, and deadline define the target?",
        "Which interim milestones are stated?",
        "Which source would resolve whether the target was met?",
    ],
}

_KEYWORDS = {
    "environmental": r"emission|carbon|co2|recycl|climate|energy|waste|sustainab|packaging|net.zero",
    "business_growth": r"revenue|growth|sales|customer|user|booking|profit|margin",
    "ai_capability": r"\bai\b|model|accura|autonom|machine learning|algorithm",
    "privacy_security": r"privacy|encrypt|security|personal data|breach",
}


def family(claim: Claim) -> str:
    if claim.assertion_type == AssertionType.future_target:
        return "future_target"
    text = " ".join(filter(None, [claim.text, claim.metric])).lower()
    for name, pattern in _KEYWORDS.items():
        if re.search(pattern, text):
            return name
    return "product_attribute"


def plan(claim: Claim, llm: LLM | None) -> list[VerificationQuestion]:
    checklist = CHECKLISTS[family(claim)]
    drafts = []
    if llm is not None:
        try:
            drafts = llm.plan_questions(claim, checklist)
        except ProviderError:
            drafts = []  # the checklist alone is still a usable plan
    if not drafts:
        return [VerificationQuestion(id=f"{claim.id}-q{i}", claim_id=claim.id, text=text,
                                     critical=i == 0) for i, text in enumerate(checklist)]
    return [VerificationQuestion(
        id=f"{claim.id}-q{i}", claim_id=claim.id, text=d.text, why_it_matters=d.why_it_matters,
        evidence_needed=d.evidence_needed, materiality=min(max(d.materiality, 1), 3),
        answerability=min(max(d.answerability, 1), 3), critical=d.critical)
        for i, d in enumerate(drafts)]
