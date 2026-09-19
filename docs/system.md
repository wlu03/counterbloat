# System

Countercheck follows `Countercheck_Complete_System.md`. This file maps the specification to the code.

| Specification | Code |
|---|---|
| 5 Claim representation, 13 Data contracts | `backend/models.py` |
| 6.1–6.2 Ingestion and anchors | `backend/ingestion/` |
| 6.3–6.4 Routing and extraction | `backend/claims/extract.py`, `backend/providers/jev.py` |
| 6.5 Verification questions | `backend/planning/checklists.py` |
| 7.1–7.2 Retrieval and discovery | `backend/retrieval/` |
| 7.3–7.4 Evidence relationships and provenance | `backend/evidence/`, `backend/verification/comparability.py` |
| 7.5–7.6 Investigation state and stopping | `backend/orchestration/worker.py`, `backend/belief/priority.py` |
| 8 Protected compression | `backend/compression/protect.py`, `backend/providers/ttc.py` |
| 9.1 Restricted calculations | `backend/verification/numeric.py` |
| 9.3 Review and supported rewrite | `backend/assessment/review.py` |
| 10.6 Linguistic state update | `backend/belief/state.py` |
| 10.7, 21 Experimental accumulator | `backend/belief/accumulator.py` |
| 11.2 Abstention by expected loss | `backend/assessment/decision.py` |
| 12 Orchestration and prompts | `backend/orchestration/worker.py`, `backend/providers/prompts.py` |
| 13.3 Endpoints | `backend/api/app.py` |
| 15 Reader | `apps/web/` |
| 16 Datasets | `datasets/` |
| 18 Evaluation | `evaluation/`, `tests/` |

## Rules the code enforces

- A claim is kept only if its quote is an exact substring of the passage it came from.
- An evidence quote must be an exact substring of a passage that was shown to the model.
- A calculation input must cite a passage that contains the number. Code runs the arithmetic.
- Evidence measured on a different basis from the claim is recorded as qualifying it, not contradicting it.
- Identical passages, and passages the analyst marks as repeating another, join one provenance group.
- A verdict with no admitted evidence becomes `insufficient`.
- A provider failure is recorded in the run manifest. It never changes an assessment.
- `Finding.probability` is always null. The accumulator in `backend/belief/accumulator.py` is for experiments.

## Not implemented

- The cumulative and tempered updaters (ablations A6 and A7) are not wired into the worker. The
  accumulator arithmetic exists and is tested.
- PDF parsing extracts page text only. It does not read tables or bounding boxes.
- The fetcher validates each address before connecting. It does not pin the connection to the
  validated address, so a DNS change between the check and the request is not covered.
- Authentication is one shared API key. There are no users or tenants.
- No result has been measured on any dataset.
