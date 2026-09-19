"""TypeSafe Jev adapter: routes a passage with one Choice question."""
from __future__ import annotations

import httpx

from backend.config import env
from backend.providers.base import ProviderError, Route

URL = "https://api.typesafe.ai/v1/systemone"

CRITERIA = {
    "reported_achievement": "States a result the company says it achieved",
    "numerical_comparison": "Compares quantities across periods, products, or companies",
    "capability": "States what a product or system can do",
    "causal_benefit": "Says an action caused a benefit",
    "product_attribute": "Describes a property of a product or its materials",
    "policy_commitment": "States a policy or commitment in force",
    "future_target": "States a goal to reach by a future date",
    "promotional": "Promotional language that cannot be tested",
    "none": "Contains no substantive assertion",
}


class JevRouter:
    def __init__(self) -> None:
        self.key = env("TYPESAFE_API_KEY")
        if not self.key:
            raise ProviderError("TYPESAFE_API_KEY is not set")

    def route(self, text: str) -> Route:
        body = {"state": text, "model": "jev-latest", "questions": {"route": {
            "type": "choice", "instructions": "Which kind of assertion does this passage make",
            "criteria": CRITERIA}}}
        try:
            response = httpx.post(URL, json=body, timeout=20,
                                  headers={"Authorization": f"Bearer {self.key}"})
            response.raise_for_status()
            answer = response.json()["answers"]["route"]
            choice = answer["choice"]
            confidence = float(answer["confidence"])
        except Exception as exc:
            raise ProviderError(f"jev route failed: {exc}") from exc
        return Route(is_claim=choice != "none", confidence=confidence)
