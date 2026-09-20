"""What each labelled dataset can measure here, using the dataset's own labels."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.models import Claim, ScoringTarget


@dataclass(frozen=True)
class VerificationTask:
    text_field: str
    label_field: str           # the gold field that holds the dataset's verdict
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


# These datasets label truth given evidence. They are not overstatement labels, so the scoring
# target of each task is the dataset's own refuted class.
VERIFICATION = {
    "averitec": VerificationTask(
        text_field="claim", label_field="label", positive="Refuted", protocol="AVeriTeC",
        hypothesis="H=1: the AVeriTeC annotators labelled this claim Refuted.",
        status_of={"Supported": "supported", "Refuted": "contradicted",
                   "Not Enough Evidence": "insufficient",
                   "Conflicting Evidence/Cherrypicking": "mixed"}),
    # The annotators judged each claim against five Wikipedia sentences, which are the
    # searchable documents of the example. DISPUTED means the sentences point both ways.
    "climate_fever": VerificationTask(
        text_field="claim", label_field="claim_label", positive="REFUTES", protocol="CLIMATE-FEVER",
        hypothesis="H=1: the CLIMATE-FEVER annotators labelled this claim REFUTES.",
        status_of={"SUPPORTS": "supported", "REFUTES": "contradicted",
                   "NOT_ENOUGH_INFO": "insufficient", "DISPUTED": "mixed"}),
    # Verdicts of professional fact-checkers on numerical claims. The dataset has no class for
    # too little evidence, so an "insufficient" finding always counts as a disagreement.
    "quantemp": VerificationTask(
        text_field="claim", label_field="label", positive="False", protocol="QuanTemp",
        hypothesis="H=1: the fact-checker's verdict on this claim, as QuanTemp records it, is False.",
        status_of={"True": "supported", "False": "contradicted", "Conflicting": "mixed"}),
}
