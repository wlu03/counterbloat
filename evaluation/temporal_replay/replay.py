"""Run the same document at several evidence cutoffs and keep later sources separate."""
from __future__ import annotations

import uuid
from datetime import datetime

from backend.evidence.ledger import admissible
from backend.models import DocumentSnapshot, Finding, Mode
from backend.orchestration.worker import Deps, run_analysis


def replay(deps: Deps, document_id: str, cutoffs: list[datetime]) -> dict[str, dict]:
    results = {}
    documents = deps.store.find("documents", DocumentSnapshot)
    for cutoff in cutoffs:
        analysis_id = f"replay-{uuid.uuid4().hex[:8]}"
        job = {"id": analysis_id, "document_id": document_id, "mode": Mode.replay.value,
               "cutoff": cutoff.isoformat(), "status": "queued"}
        deps.store.put("analyses", analysis_id, job, document_id=document_id)
        run_analysis(analysis_id, deps)
        results[cutoff.isoformat()] = {
            "findings": deps.store.find("findings", Finding, analysis_id=analysis_id),
            # Sources first available after the cutoff are listed here and were not used.
            "later_documents": [d.id for d in documents if not admissible(d, Mode.replay, cutoff)],
        }
    return results
