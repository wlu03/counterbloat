# ASA integration into the public benchmark kit

## Delivered

The uploaded ASA pack is now a fourth dataset in the shared benchmark harness. Use `--dataset asa` with `--mode retrospective` or `--mode independent`. ASA data are **preloaded**; FinQA, FinanceBench, and AVeriTeC retain their prior pinned download scripts and are **not** preloaded.

### Contents actually transformed

| Item | Count / status |
|---|---|
| Unique assertion records | 30 |
| Original rulings represented | 24 |
| Company groups | 23 |
| Retrospective summary passages | 30 |
| Independent evidence documents | 0 |
| Adjudicated reference assessments | 0 |
| Draft material labels | present 20; absent 7; undetermined 3 |
| Draft evidence labels | mixed 19; supported 7; insufficient 3; contradicted 1 |

These are counts from the uploaded files, not newly verified findings about companies. Two modes provide different views of the same 30 records, not 60 independent examples.

## Standardization performed

The ASA pack now uses the same `example_id`, `dataset`, `task`, prediction `status`, JSONL layout, adapter function, and `benchmark.py` commands as the earlier kits. Runtime files, evaluator-only references, source manifests, and output metrics have consistent locations.

The native ASA claim ID is preserved unchanged. `original_claim_excerpt` becomes `claim`; the excerpt/context qualifications remain explicit. Material-overstatement and evidence-status labels are normalized separately to lowercase. Ruling outcomes are preserved as native metadata and are **not** relabeled as true/false or overstatement. Native source files remain available for round-trip checks.

Summary document IDs are namespaced by assertion because some original summary IDs were reused for different issue-specific texts. Every normalized passage retains its native document ID, source URL, date, locator, and content hash. Namespaced IDs do not make related summaries independent evidence.

Two complete mode-specific directory trees prevent retrospective summaries from sitting inside the independent runtime packet. Model inputs exclude compiler draft labels and reference annotations. The retrospective corpus still intentionally contains answer-bearing summaries and is marked accordingly.

## What can be tested now

**Retrospective interpretation and application wiring:** run a model on the claim/context and supplied summary, then explicitly opt into `--allow-draft` to compare its output with unreviewed project-rubric drafts. Results identify themselves as provisional, not a validated benchmark result.

**Independent claim ingestion:** inspect or export the independent candidates. Running or scoring an independent detector is blocked because the supplied pack has no admitted independent evidence, original-ad captures, or adjudication. These missing materials were not invented during integration.

## New compatibility tools

`import-predictions` accepts the original ASA prediction format and normalizes label spellings and evidence IDs. `native-export` reverses the mapping for completed records and the original local scorer. `review-sheet` produces a blank reviewer/adjudication worksheet around model outputs without promoting any labels to gold. `export-runtime` creates a one-mode source-only archive.

Shared scoring keeps missing/error/pending/abstained outputs in the declared denominator. It reports separate material/evidence/joint accuracy, macro-F1, confusion matrices, coverage, false-adverse-finding diagnostics, company-macro accuracy, and optional probability diagnostics. Citation-ID validity is not citation entailment; semantic correctness remains review-dependent.

## Validation

**95 shared-kit unit tests, 30 CLI checks, and 10 original ASA scorer tests passed.** Both prepared ASA views passed count, ID, allowlist, mode, and checksum checks. Python compilation succeeded. Source archive bytes and member checksums were preserved.

No model evaluation, public data download, independent investigation, or reference adjudication was run. Perfect results on explicit label-identity fixtures are software tests only. See `VALIDATION_REPORT.md` and the logs for exact validation scope.
