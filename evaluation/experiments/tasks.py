"""What each labelled dataset can measure here, using the dataset's own labels."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.models import Claim, ScoringTarget


@dataclass(frozen=True)
class VerificationTask:
    text_field: str
    status_of: dict[str, str]  # dataset verdict -> the evidence status that corresponds to it
    positive: str              # the dataset label that the scoring target's H=1 stands for
    hypothesis: str
    protocol: str

    def target(self, claim: Claim, cutoff: datetime | None) -> ScoringTarget:
        return ScoringTarget(id=f"{self.protocol}-{self.positive}".lower().replace(" ", "-"),
                             claim_id=claim.id, claim_version=claim.version,
                             hypothesis=self.hypothesis, rubric=claim.rubric, cutoff=cutoff,
                             label_space=[self.positive, f"not {self.positive}"],
                             protocol=self.protocol)


# AVeriTeC verdicts are about truth given evidence. They are not overstatement labels, so the
# scoring target for this task is the dataset's own Refuted label.
VERIFICATION = {"averitec": VerificationTask(
    text_field="claim", positive="Refuted", protocol="AVeriTeC",
    hypothesis="H=1: the AVeriTeC annotators labelled this claim Refuted.",
    status_of={"Supported": "supported", "Refuted": "contradicted",
               "Not Enough Evidence": "insufficient",
               "Conflicting Evidence/Cherrypicking": "mixed"})}
