# System

Countercheck follows `Countercheck_Complete_System.md`. This file maps the specification to the code.

| Specification | Code |
|---|---|
| 5 Claim representation, 13 Data contracts | `backend/models.py` |
| 6.1–6.2 Ingestion and source locations | `backend/ingestion/`; a claim stores its passage id, exact text, and offsets |
| 6.3–6.4 Routing and extraction | `backend/claims/extract.py`, `backend/providers/jev.py` |
| 6.5 Verification questions | `backend/planning/checklists.py` |
| 7.1–7.2 Retrieval and discovery | `backend/retrieval/` |
| 7.3–7.4 Evidence relationships and provenance | `backend/evidence/`; the analyst names the fields on which a passage differs from the claim, and `backend/orchestration/worker.py` acts on that |
| 7.5–7.6 Investigation state and stopping | `backend/orchestration/worker.py`, `backend/belief/priority.py` |
| 8 Protected compression | `backend/compression/protect.py`, `backend/providers/ttc.py` |
| 9.1 Restricted calculations | `backend/verification/numeric.py` |
| 9.3 Review and supported rewrite | `backend/assessment/review.py` |
| 10.6 Linguistic state update and the verdict rule | `backend/belief/state.py` |
| 10.7, 21 Updating strategies, evidence scorer, accumulator | `backend/belief/strategies.py`, `backend/belief/accumulator.py`; see `docs/belief_updating.md` |
| 12 Orchestration and prompts | `backend/orchestration/worker.py`, `backend/providers/prompts.py` |
| 13.3 Endpoints | `backend/api/app.py` |
| 15 Reader | `apps/web/` |
| 16 Datasets | `datasets/` |
| 18 Evaluation | `evaluation/`, `tests/`; commands in `docs/evaluation_protocol.md` |

## Rules the code enforces

- A claim is kept only if its quote is an exact substring of the passage it came from.
- An evidence quote must be an exact substring of a passage that was shown to the model.
- A calculation input must cite a passage that contains the number. Code runs the arithmetic.
  One tokenizer decides what a written number means for both parsing and matching. In a table a
  bracketed amount is a negative, so `(1,577)` holds -1577 and not 1577; in a sentence the
  brackets may be an aside, so both readings are accepted there.
- A result carries the period, population, and boundary of what it was computed from, so
  multiplying a value by a scale factor cannot strip the metadata a later comparison checks. A
  scale factor has no period or scope of its own and does not erase the other operand's.
- Two programs are the same calculation only when they read the same numbers from the same
  passages, combine them in the same order with the same operations, and offer the same result
  to the claim. `divide(a, b)` and `divide(b, a)` are different calculations. A program that
  failed to execute does not block a later program over the same numbers.
- A claim that states a bound, such as "at least 40%" or "below 5%", is tested against the bound
  and not for equality. A bound counts only where it is written beside the number it bounds. A
  claim that states two endpoints, and a result whose sign convention differs from the claim's,
  are recorded as not testing the claim.
- Evidence measured on a different basis from the claim is recorded as qualifying it, not contradicting it.
- Identical passages, and passages the analyst marks as repeating another, join one provenance group.
- Evidence, answers, and verified calculations of a round are recorded before the updater runs.
  Each calculation is recorded once. If the updater fails, they stay recorded and no assessment
  transition is written. A retry with the same input records no second update.
- A passage measures something other than the claim only on a basis the claim states. A claim
  that names no period cannot be measured over a different period. Denominator, population and
  boundary are the exception: a claim that names none of them is a claim about the whole, so a
  passage about a part does measure something else. A difference that is ignored is listed under
  `rejections`.
- Each evidence item keeps the analyst's own reading in `judged` beside the `relationship` a
  difference of basis rewrote, so the updater reads both.
- The updater is asked `assessment.updater_samples` times and the status its samples agree on
  most often is used. It is 1 by default and 3 in `config/evaluation.yaml`.
- A verdict needs admitted, comparable evidence about the claim in its own direction, or a
  calculation whose result code compared with the value the claim states. A calculation that
  answers a side question does not justify a verdict. Otherwise the status becomes
  `insufficient`. A review can weaken a verdict but not strengthen it. The summary was written
  for the status the model proposed, so when the gate rejects that status the summary is
  replaced with a fixed sentence. The model's own wording stays in the update's explanation.
- In live mode the analysis looks outside the claim's document while a critical question is
  still open, or while nothing was retrieved at all. The query names the questions being worked
  on, and each query is asked once per investigation. Where a passage came from does not say
  whether the questions are answered, so it does not decide this.
- A review cannot grant a verdict, because only evidence passing the verdict gate can. A review
  that asks for a firmer conclusion than the investigation reached is treated as a request for a
  check, so what it says is missing is searched for instead of discarded.
- When the review asks for a check, the request becomes a critical question and gets at most
  `max_follow_up_rounds` further rounds, then a second review. A check that was still not
  completed is listed in the finding. The report is written from the reviewed assessment.
- A withdrawal or correction removes the item from the active ledger and keeps it in the
  history. A calculation is removed when a group it read from is no longer active, or when it
  cites the withdrawn passage and no admitted item cites that passage any more.
- The claim's own sentence is not accepted as evidence for the claim.
- The finding summary may use only numbers found in the claim, the evidence passages, or the
  calculation outputs, and is replaced by a fixed sentence otherwise. The supported rewrite says
  what the evidence establishes, so a figure that appears only in the claim under test does not
  support it and the rewrite is dropped. This is what stops a contradicted claim from being
  rewritten back into its own number. The report is written after the review, so the number rule
  is the only check on its wording; nothing checks that the wording follows from the evidence.
- Every rate the experiment scorer reports is over the claims that ran. The claims that did not
  run are counted as `not_run`, and `status_agreement_all` and `coverage_all` are the same rates
  over every claim the run was given.
- Model output that fails validation is listed under `rejections` in the run manifest. It does
  not make a job partial. Operational failures are listed under `errors` and do.
- A failed OpenAI, Jev, or Token Company call during an analysis is recorded in the run manifest
  and never changes an assessment. A failed embedding call is not recorded; search then uses
  keywords only.
- A job with recorded errors is stored as partial. A cancelled job is stored as cancelled.
- Replication of linked code (`backend/replication/replicate.py`, `backend/providers/devin.py`).
  When an analysis is created with `replicate: true`, is in live mode, and Devin is configured,
  one Devin session per linked GitHub or GitLab repository (at most `replication.max_repositories`)
  clones it, runs its code, and returns measured values with their conditions, the commands, the
  commit, and every deviation. The session is given none of the organisation's secrets or
  knowledge, has an ACU limit and a time limit, and is stopped when the time limit passes. The
  report is stored as a source document and cited like any other: its figures pass the quote
  check, the number rule, and the verdict rule. A replication that could not run, gave no result,
  or failed to start is recorded under `errors` and is not evidence against the claim. The
  repository's text is treated as material under test, and every string from the session is
  escaped before it is stored. Limits: one automated run on one machine is weak evidence about a
  claim that depends on hardware, seeds, or long training; Devin can make mistakes, which is why
  the report lists commands and deviations; the post itself must be pasted, because nothing here
  fetches from X.
- `Finding.probability` is always null. Internal scores are stored with their target and method,
  are left out of the public endpoints, and are served by `GET /claims/{id}/research` only when
  `COUNTERCHECK_RESEARCH_VIEW` is set.
- An accumulated score is produced only when every active scoring unit has a score that applies
  to the current context. A unit whose score failed, or whose score is stale, makes the score
  unavailable rather than being left out of it, so a failed provider call cannot be read as the
  prior or as the surviving side of a balanced pair. The units that were scored are still
  listed. A score that names no admitted evidence is rejected.
- A repeated passage is one observation. Members of a scoring unit are collapsed on their quote
  and reading before the unit is scored, so a second copy neither changes the conditioning
  context nor causes a second scorer call.
- The fingerprint that decides whether a round has anything new to decide on covers the claim
  and its qualifications, the evidence, the calculations, the answers, the strategy and its
  sample count, the prior and tempering, the target, and the model and scorer versions. A change
  to any of them runs the round again.

## Not implemented

- No calibrator exists, because no labelled reference reviews exist for the overstatement
  target. `calibrated_probability` is always null. The only evidence scorer is the
  language-model estimate. No learned or validated observation model exists.
- No API endpoint withdraws, corrects, or merges evidence. Those operations are exercised by
  the replay harness and the tests.
- Abstention by expected loss (section 11.2) is not implemented. It needs a calibrated probability.
- PDF parsing extracts page text in file order and splits it into passages of about 800
  characters at sentence ends. It does not read tables or bounding boxes. A page with no
  text layer is read by an OpenAI vision call and the document gets the `ocr_text` flag. Without
  OpenAI, or for a PDF sent as `content` (JSON cannot carry its bytes), it gets `no_text_layer`.
- HTML tables are read on a column grid that follows `colspan` and `rowspan`. Header rows are
  found by content: `<th>` rows, bracketed notes, title rows, and rows without figures above the
  data, which is how filings write period labels. A currency sign, a percent sign, a closing
  bracket, or a range dash in a cell of its own is joined to its number. Checked against four
  filings (Apple, Disney, and Microsoft 10-K, Tesla 10-Q): every number has a column label in 94%
  to 100% of the rows that hold numbers. Known limits: a table whose header is in a separate
  `<table>` above it keeps its figures without labels, because borrowing labels could attach a
  wrong period; a table with no label column loses the header of its first column; a header
  row is recognised by rules of thumb (length, digits, years), which other layouts can defeat.
- Authentication is one shared API key. There are no users or tenants.
- The run manifest records the commit, the updater, model identifiers, the prompt and checklist
  versions, the configuration hash, the cutoff, OpenAI, Jev, and Token Company calls with token
  counts (latency for all but embedding and discovery calls; a failed embedding or discovery
  call is not recorded as a call), passages that routing excluded, compression fallbacks, whether every
  search of the analysis used vectors, errors, and rejections. It does not record SDK versions or a corpus
  hash. Cost is computed by the scoring step from a price list the user supplies, and is
  reported as unknown without one.
- Jev and Token Company calls are tried once. A job runs as a FastAPI background task and cannot
  resume, so a server restart leaves it `running`.
- `Claim.version` is always 1. A newly found qualification does not create a new claim version.
- The interactive API pages at `/docs` and `/openapi.json` do not require the API key.
- sec.gov answers 403 unless `FETCH_USER_AGENT` names a contact in the form SEC asks for. bp.com
  refuses automated requests. Documents from a site that refuses the fetcher must be uploaded.
- Text made block-level only by CSS is joined without a space. A claim that appears only in a
  table cell is not extracted, because table rows are evidence passages, not claim candidates.
- A review rejection always produces `insufficient`, so a reviewer who rejects an assessment for
  being too weak still weakens it. The comparison in `docs/evaluation_protocol.md` has one case
  that is wrong for this reason. A reviewer who instead narrows towards a firmer status no longer
  has that request dropped: it becomes a critical question and gets the follow-up rounds, and the
  verdict gate then decides what the evidence earns.
- No path in the code raises an assessment. The updater proposes a status and every later stage
  (the comparability rule, the verdict gate, the reviewer) can only weaken it. On the measured
  runs this is mostly not what abstains: of 53 abstentions the updater proposed `insufficient`
  in 49, the verdict gate demoted a verdict in 2, and the reviewer in 2.
- Measured against a one-search one-judgment baseline on QuanTemp and CLIMATE-FEVER, the pipeline
  commits to fewer claims and is less often right when it commits. See
  `docs/evaluation_protocol.md`. What it does give is grounding: on FinQA every figure it used
  was verifiably in the passage it cited.
- No dataset file is present in this repository; `datasets/*/downloads/` and the labels are
  ignored by git. The results that have been measured are in `docs/evaluation_protocol.md`, on
  samples of 40 to 60 claims. FinQA and FinanceBench are questions, not claims, so the
  verification runner does not take them; FinQA is run by `evaluation/experiments/finqa.py`
  instead. GreenClaims accusations are annotations, not adjudicated labels, so no metric is
  computed from them.
