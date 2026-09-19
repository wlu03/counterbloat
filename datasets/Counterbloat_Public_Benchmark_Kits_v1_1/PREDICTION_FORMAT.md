# Prediction contracts

Each line in the prediction JSONL is one JSON object with the exact `example_id` from `runtime/inputs.jsonl`. Duplicate and unknown IDs are rejected. Missing predictions count as wrong in the declared verdict/answer denominator. Use `status="ok"` for a completed output, `abstained` for a deliberate abstention, and `error` plus an error message for operational failure.

## FinQA

```json
{"example_id":"COPY_THE_REAL_ID","status":"ok","answer":0.1,"predicted_program":["subtract(","110","100",")","divide(","#0","100",")","EOF"],"evidence_ids":["table_1"]}
```

The illustrated numbers/ID are synthetic. Use the official operation names and token syntax. Step references are zero-based (`#0` is the first step). `answer` uses the original task's numeric scale; e.g. 10% is the fraction 0.1 when that is the requested quantity. The primary scorer executes `predicted_program`, not the model's asserted answer. Evidence IDs are retained but automatic source-entailment correctness is not claimed. Unit labels and source boundaries still need review.

## FinanceBench

```json
{"example_id":"COPY_THE_REAL_ID","status":"ok","answer":"Reported revenue was 110 million.","citations":[{"doc_name":"Fictional_2020_10K","page_index":0,"quote":"Revenue was 110 million."}]}
```

This is a synthetic schema illustration. `page_index` is the physical PDF page position, **zero-based**, not a printed page label. `doc_name` must match the source document identifier. The local page-overlap diagnostic compares these locators, not the semantic meaning of quotes. Human review is required for answer/citation correctness.

## AVeriTeC

```json
{"example_id":"averitec-dev-0000","status":"ok","label":"Supported","evidence":[{"question":"What does the source establish?","answer":"A source-grounded answer.","url":"https://example.org/source"}],"probabilities":{"Supported":0.7,"Refuted":0.1,"Not Enough Evidence":0.15,"Conflicting Evidence/Cherrypicking":0.05}}
```

This is a format illustration, **not a prediction for actual dev claim 0**. The native label names are:

- `Supported`
- `Refuted`
- `Not Enough Evidence`
- `Conflicting Evidence/Cherrypicking`

`Conflicting Evidence/Cherry-picking` is normalized to the last spelling for compatibility. No other labels are silently remapped. Optional probabilities must contain exactly these four labels, be finite, lie in [0,1], and sum to 1. They estimate this task's native verdict distribution, not deceptive intent. Omit the field or set it to null when unavailable. Probability metrics report their own coverage.

The evidence-conditioned official evaluator expects generated question/answer pairs, not only URLs. The kit's exporter orders predictions against references, includes missing cases, and gives absent evidence an empty placeholder to avoid upstream empty-list failures. Its additional `claim_id` is the original zero-based dev row index. Preserve this mapping when querying the FEVER-7 knowledge store.

## Optional instrumentation

Add model name/version, prompt hash, source IDs, updater mode, cost, and token counts as extra prediction fields. The current local scorers preserve the predictions but do not infer unknown provider cost from token counts. Compare runs under the same corpus and declared ID selection.

## ASA (added in v1.1)

```json
{"example_id":"COPY_THE_ASA_CLAIM_ID","dataset":"asa","mode":"retrospective","status":"ok","material_overstatement":"undetermined","evidence_status":"insufficient","probabilities":null,"explanation":"A source-grounded interpretation of the permitted summary.","evidence_ids":["COPY_AN_ALLOWED_NAMESPACED_DOCUMENT_ID"],"supported_rewrite":null}
```

This is a schema illustration, not an answer for a real record. `example_id` is identical to the original ASA `claim_id`. `mode` is required and must match the selected packet. Material labels are `present`, `absent`, `undetermined`; evidence labels are `supported`, `contradicted`, `mixed`, `insufficient`, `not_yet_resolvable`. Do not substitute native ASA ruling decisions for either target.

Evidence IDs come from `allowed_evidence_ids` and are namespaced by assertion. Native IDs such as `R17-summary` can refer to different issue summaries in the original pack, so use the normalization importer rather than guessing IDs. Invalid citations are reported as locator errors; valid IDs do not establish semantic entailment.

Optional `probabilities` maps exactly the three lowercase material labels to finite values in [0,1], summing to 1; the chosen material label must maximize them. Missing probabilities leave calibration metrics unavailable. `undetermined` is a legitimate rubric prediction; `status="abstained"` is a separate operational choice.

`pending`, `abstained`, and `error` predictions need no label fields but must retain `example_id` and `mode`. They stay in the declared denominator. All supplied ASA references are drafts; completed predictions can only receive a **provisional retrospective comparison** with explicit `--allow-draft`. Full schema: `schema/asa_prediction.schema.json`.
