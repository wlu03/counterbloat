# Standardization contract

## Shared interfaces, not a fabricated common label

All four datasets use `benchmark.py` with the same prepare/validate/select/template/run/score entry points and `predict(example, runtime_dir) -> dict` adapter. Every record has a stable string `example_id`, `dataset`, and `task`. Prediction status uses `ok`, `pending`, `abstained`, or `error`. Missing and failed cases stay in the declared denominator.

FinQA's answer/program target, FinanceBench's answer/citation target, and AVeriTeC's native verdict space are unchanged. ASA adds `task="corporate_claim_assessment"` and its two-axis rubric. There is no universal `true/false` mapping or aggregated four-dataset accuracy.

## ASA mappings

| Source | Standardized |
|---|---|
| `claim_id` | `example_id` with exactly the same value; `claim_id` retained |
| `original_claim_excerpt` | `claim` |
| `context_paraphrase` and representation flags | Preserved verbatim; not described as the full ad |
| `observed_date` and precision | Preserved; null dates remain null |
| `independent_assessment_cutoff` | `assessment_cutoff` only in independent mode |
| Retrospective `assessment_cutoff` | Preserved in retrospective mode only |
| `allowed_evidence_documents[]` | `runtime/corpus/passages.jsonl`, scoped by `example_id` |
| Native `document_id` | `<claim_id>:<native_document_id>`; native ID retained in `source_document_id` |
| `draft_material_overstatement` | Evaluator-only lowercase `present / absent / undetermined` |
| `draft_evidence_status` | Evaluator-only `supported / contradicted / mixed / insufficient / not_yet_resolvable` |
| Native issue findings and ruling decisions | Preserved evaluator-only; not converted into truth labels |
| Company/campaign/ruling grouping | Evaluator-only references and `id_mapping.jsonl` |
| Review flags and null assessments | Preserved; not promoted to adjudicated |

## ASA mode isolation

`data/asa/retrospective/runtime` includes answer-bearing compiler summaries, explicitly marked. `data/asa/independent/runtime` contains only the source pack's claim candidates and an empty corpus. The two modes occupy different filesystem roots. Do not mount their shared parent as the model's source directory.

Raw source data and review workbook remain in `bundled/ASA_test_pack_2026-09-19.zip`, byte-for-byte. SHA256: `95119566d269a3194bff913fda98cb65f9a461a9e53dcf99ee0d0b871d8f3157`.

The prepared files carry hashes. Validation checks field allowlists, mode alignment, source identity, evidence references, document hashes, and unexpected runtime files. It does not prove that source facts are correct or establish historical availability.

## Metrics

ASA's main rates use the full declared ID selection. An absent/error output is an incorrect or missing prediction, not silently excluded. Probability metrics and citation diagnostics report their own coverage. An empty cited set is not counted as valid corroboration.

Per-class zero-denominator precision/recall/F1 follow the existing kit's zero convention. Macro-F1 averages over all fixed labels, including labels absent in a small subset. Do not confuse this with the original ASA scorer's supported-classes macro-F1. Original labels/format can be exported for a separately named native-score comparison.

Neither a correct draft label nor a valid citation ID establishes correct reasoning. Semantic review columns are supplied but not automatically graded. No synthetic corporate examples were added to the 30-record ASA collection.

Namespaced document IDs identify assertion-specific summary views, not independent measurements. Several such IDs can refer to one underlying ruling. Preserve the original URL/ruling provenance when deduplicating evidence; do not count 30 summary IDs as 30 independent confirmations.
