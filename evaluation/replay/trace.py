"""A fixed sequence of evidence events for one claim, saved so that it can be replayed.

Usage: python -m evaluation.replay.trace ANALYSIS_ID CLAIM_ID --out trace.json
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from backend.config import env
from backend.db import Store
from backend.models import Calculation, Claim, EvidenceItem, InvestigationState, VerificationQuestion


class Event(BaseModel):
    kind: Literal["admit", "calculate", "withdraw", "correct", "merge"]
    evidence: EvidenceItem | None = None    # admit, and the replacement item of a correction
    calculation: Calculation | None = None  # calculate
    evidence_id: str | None = None          # withdraw and correct: the item that is removed
    group_ids: list[str] = []               # merge: the group kept, then the group dropped


class Trace(BaseModel):
    id: str
    claim: Claim
    questions: list[VerificationQuestion] = []
    cutoff: datetime | None = None
    events: list[Event]
    # Recorded log-evidence per evidence id. Only the scripted provider reads it.
    scripted_scores: dict[str, float] = {}
    source: str = ""
    is_synthetic_example: bool = False


def export_trace(store: Store, analysis_id: str, claim_id: str) -> Trace:
    """Rebuild the event sequence of a stored investigation from its final state.

    Evidence and calculations are ordered by the round that produced them. Items withdrawn
    during the run are not exported.
    """
    state = store.get("states", f"{analysis_id}-{claim_id}", InvestigationState)
    manifest = store.get("manifests", analysis_id) or {}
    events = []
    for number in sorted({e.round for e in state.evidence} | {c.round for c in state.calculations}):
        events += [Event(kind="admit", evidence=e) for e in state.evidence if e.round == number]
        events += [Event(kind="calculate", calculation=c)
                   for c in state.calculations if c.round == number]
    members = {g.id: g.member_ids for g in state.groups}
    scores = {i: s.log_evidence for s in state.scores for i in members.get(s.group_id, [])}
    return Trace(id=f"{analysis_id}-{claim_id}", claim=state.claim, questions=state.questions,
                 cutoff=state.target.cutoff if state.target else None, events=events,
                 scripted_scores=scores,
                 source=f"analysis {analysis_id} at commit {manifest.get('commit')}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("analysis_id")
    parser.add_argument("claim_id")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    store = Store(env("DATABASE_URL", "sqlite:///countercheck.db"))
    trace = export_trace(store, args.analysis_id, args.claim_id)
    Path(args.out).write_text(trace.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
