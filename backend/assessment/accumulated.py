"""Put one claim's agent findings into the shape the belief ledger reads, and score them.

The five agents each return a finding about one claim. The ledger works on evidence items held in
groups, scores each group once, and adds the scores as log evidence. Putting the findings into
that shape means a passage quoted twice counts once, and a filed figure can weigh more than a
passage that merely mentions the same subject.

The score this produces is uncalibrated. `config` refuses to put a number in public output, and
this does not change that: the value belongs in the research view, beside what it was built from.
"""
from __future__ import annotations

from datetime import datetime

from backend.belief.strategies import accumulate, new_target, score_groups
from backend.config import AssessmentSettings
from backend.models import (
    Claim, EvidenceGroup, EvidenceItem, EvidenceOrigin, InvestigationState, NumericBelief,
    Relationship, RunManifest,
)

# What an agent said about the claim, in the ledger's terms. A finding that takes no side is
# context: it is recorded and shown, and it moves the score by whatever the scorer decides.
RELATIONSHIPS = {"contradicts": Relationship.contradicts, "supports": Relationship.supports,
                 "neutral": Relationship.context, "context": Relationship.context}
# A filed figure and a passage of the filing are both the company's own account of itself.
ORIGINS = {"structured": EvidenceOrigin.company_reported,
           "filing_text": EvidenceOrigin.company_reported,
           "peer_comparison": EvidenceOrigin.other,
           "external": EvidenceOrigin.regulatory_finding}


def _source(finding: dict) -> str:
    """What the finding rests on. Two findings resting on the same thing share a group."""
    return str(finding.get("quote") or finding.get("tag") or finding.get("prior_quote")
               or finding.get("accession") or finding["agent"])[:120]


def state_for(claim: Claim, findings: list[dict], cutoff: datetime | None = None
              ) -> InvestigationState:
    """One claim, its findings as evidence, and one group per thing a finding rests on."""
    evidence: list[EvidenceItem] = []
    members: dict[str, list[str]] = {}
    for i, finding in enumerate(findings):
        if finding.get("stance") == "not_found":
            continue  # Nothing was found, so there is nothing to weigh.
        item_id = f"{claim.id}-e{i}"
        evidence.append(EvidenceItem(
            id=item_id, claim_id=claim.id, span_id=finding.get("span_id") or item_id,
            document_id=finding.get("accession") or finding["agent"],
            quote=str(finding.get("quote") or finding.get("note") or finding["agent"]),
            relationship=RELATIONSHIPS.get(finding.get("stance", ""), Relationship.context),
            target="claim",
            origin=ORIGINS.get(finding.get("tier", ""), EvidenceOrigin.other)))
        members.setdefault(_source(finding), []).append(item_id)
    groups = [EvidenceGroup(id=f"{claim.id}-g{n}", member_ids=ids)
              for n, (_, ids) in enumerate(sorted(members.items()))]
    by_item = {item: group.id for group in groups for item in group.member_ids}
    evidence = [e.model_copy(update={"group_id": by_item[e.id]}) for e in evidence]
    return InvestigationState(claim=claim, target=new_target(claim, cutoff), evidence=evidence,
                              groups=groups)


def probability_for(claim: Claim, findings: list[dict], llm, manifest: RunManifest,
                    settings: AssessmentSettings | None = None,
                    cutoff: datetime | None = None) -> NumericBelief | None:
    """Score each group of findings and add them. None when nothing could be scored."""
    settings = settings or AssessmentSettings()
    state = state_for(claim, findings, cutoff)
    if not state.groups:
        return None
    score_groups(state, llm, manifest)
    if not state.scores:
        return None
    return accumulate(state, settings)
