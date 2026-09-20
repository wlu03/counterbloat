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
    # How this dataset's annotators decided, in the words the planner and the updater are given.
    # It states which statuses the dataset uses and what counts as enough evidence. It names no
    # label for any particular claim, so it is available at inference time.
    rubric: str = ""

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
        rubric="Decide whether the claim is true as worded, using the retrieved sources. Use"
               " supported when they show it holds, contradicted when they show it does not,"
               " mixed when they point both ways, and insufficient only when they do not bear"
               " on the claim at all. Judge the claim's main assertion. A detail the sources"
               " leave open does not by itself make the evidence insufficient.",
        status_of={"Supported": "supported", "Refuted": "contradicted",
                   "Not Enough Evidence": "insufficient",
                   "Conflicting Evidence/Cherrypicking": "mixed"}),
    # The annotators judged each claim against five Wikipedia sentences, which are the
    # searchable documents of the example. DISPUTED means the sentences point both ways.
    "climate_fever": VerificationTask(
        text_field="claim", label_field="claim_label", positive="REFUTES", protocol="CLIMATE-FEVER",
        hypothesis="H=1: the CLIMATE-FEVER annotators labelled this claim REFUTES.",
        rubric="Decide the claim against the Wikipedia sentences provided, which are the whole"
               " of the evidence. Use supported when they show the claim holds, contradicted"
               " when they show it does not, and mixed when they point both ways. Use"
               " insufficient only when no sentence bears on the claim. The sentences were"
               " chosen because they bear on it, so they will usually settle it; a qualification"
               " they leave open does not make them insufficient.",
        status_of={"SUPPORTS": "supported", "REFUTES": "contradicted",
                   "NOT_ENOUGH_INFO": "insufficient", "DISPUTED": "mixed"}),
    # Verdicts of professional fact-checkers on numerical claims. The dataset has no class for
    # too little evidence, so an "insufficient" finding always counts as a disagreement.
    "quantemp": VerificationTask(
        text_field="claim", label_field="label", positive="False", protocol="QuanTemp",
        hypothesis="H=1: the fact-checker's verdict on this claim, as QuanTemp records it, is False.",
        status_of={"True": "supported", "False": "contradicted", "Conflicting": "mixed"}),
}
