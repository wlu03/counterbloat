# Counterbloat unified benchmark kit — v1.1

This update adds the uploaded **ASA assertion-level starter pack** to the existing FinQA, FinanceBench, and AVeriTeC harness. It standardizes interfaces, IDs, prediction envelopes, separation of model inputs from references, and evaluation commands. It **does not** combine different tasks into one label space or a single accuracy score.

## What is included

| Dataset | Collection | Data in this ZIP? | Task / status |
|---|---|---|---|
| FinQA | Expected 1,147 labeled public-test examples | No; existing pinned download | Financial numerical QA |
| FinanceBench | Expected 150 public examples | No; existing pinned download | Financial report QA; semantic review needed |
| AVeriTeC | Expected 500 FEVER-7 development examples | No; existing pinned download | Claim verification; local dev evaluation, not blind test |
| ASA | **30 unique assertions from 24 rulings** | **Yes; normalized records and original source archive** | Retrospective interpretation with unreviewed draft references |

ASA has **two views of the same 30 assertions**, not 60 independent examples:

* `retrospective`: 30 short answer-bearing compiler summaries are supplied. Can test summary interpretation and output handling. Requires `--allow-draft` for scoring.
* `independent`: claim/context candidates with **zero admitted evidence documents**, no original-ad captures, and no adjudicated references. Useful for ingestion and further curation. Independent inference and scoring are intentionally blocked.

The source's material-overstatement drafts are present=20, absent=7, undetermined=3. There are zero reviewed reference assessments. These are the compiler's project labels, not official ASA classifications and not verified gold labels. No new claims, source evidence, or adjudications were invented during normalization.

## Quick start

Python **3.10+**. Unzip and open a terminal in the package directory. ASA requires no network or third-party Python packages.

```bash
python -m unittest discover -s tests -v
python benchmark.py validate --dataset asa --mode retrospective
python benchmark.py validate --dataset asa --mode independent
```

ASA packets are already prepared. To rebuild in a new directory from the preserved uploaded archive:

```bash
python benchmark.py prepare --dataset asa --mode retrospective --data-dir rebuilt/asa_retrospective --accept-license
```

Preparation verifies the archive SHA256 and the original pack's member checksums. It preserves native IDs and source text. It refuses to mix two modes in one directory or silently overwrite curated packet files. An unchanged re-preparation is idempotent.

For the original three datasets, the existing commands remain valid:

```bash
python benchmark.py prepare --dataset finqa --accept-license
python benchmark.py prepare --dataset financebench --accept-license
python benchmark.py prepare --dataset averitec --accept-license
```

These commands download source data on your machine. Read `guides/FINQA.md`, `guides/FINANCEBENCH.md`, and `guides/AVERITEC.md` for additional evidence-corpus downloads and scoring dependencies. No new live downloads or model evaluation were performed in this update.

## Shared storage and inference boundary

```text
data/
  finqa/                       # Created by the existing prepare command
  financebench/                # Created by the existing prepare command
  averitec/                    # Created by the existing prepare command
  asa/
    retrospective/             # Included and validated
      runtime/
        inputs.jsonl
        metadata.json
        corpus/passages.jsonl
      evaluator_only/
        references.jsonl
        native_references.json
        id_mapping.jsonl
        upstream_manifest.json
        UPSTREAM_README.md
      manifest.json
    independent/               # Included claim candidates; evidence corpus is empty
      runtime/...
      evaluator_only/...
      manifest.json
bundled/
  ASA_test_pack_2026-09-19.zip   # Original user-uploaded bytes, including review workbook
```

**Never index or expose the entire package to your inference model.** Supply only the selected mode's `runtime/`. The `bundled/`, `evaluator_only/`, guide, and review files contain answers or reference descriptions. Retrospective runtime deliberately contains answer-bearing summaries; its metadata says so. Independent runtime contains neither summaries nor ruling URLs.

Separate folders and Python function boundaries are not a security sandbox. Mount runtime alone in a separate process/container for enforced isolation. To export one mode:

```bash
python benchmark.py export-runtime --dataset asa --mode retrospective --output outputs/asa.retrospective.runtime.zip
python benchmark.py export-runtime --dataset asa --mode independent --output outputs/asa.independent.candidates.zip
```

The second export is an ingestion/curation packet, not a complete detection test. The explicit mode is carried into inputs, predictions, manifests, selections, and metrics. The harness rejects mode mismatches.

## One adapter interface for all four tasks

```python
from pathlib import Path

def predict(example: dict, runtime_dir: Path) -> dict:
    # Route using example['dataset'] and example['task'].
    # Read evidence only from runtime_dir / 'corpus'.
    # Return the task-specific fields in PREDICTION_FORMAT.md.
    ...
```

Financial QA must not be routed to a document claim-extraction endpoint. AVeriTeC keeps its four native verdict labels. ASA keeps two distinct outputs: `material_overstatement` and `evidence_status`.

```bash
python benchmark.py run --dataset asa --mode retrospective --adapter my_adapter:predict --output outputs/asa.predictions.jsonl
python benchmark.py score --dataset asa --mode retrospective --allow-draft --predictions outputs/asa.predictions.jsonl --output outputs/asa.metrics.json
```

`example_asa_adapter.py` includes a request builder that resolves only the passages allowed for the current assertion. Its `predict` deliberately abstains. Running it tests wiring without calling a model:

```bash
python benchmark.py run --dataset asa --mode retrospective --adapter example_asa_adapter:predict --output outputs/asa.abstentions.jsonl
```

Do not interpret the abstention fixture's scores as model performance. Unknown or duplicate IDs fail. Missing, failed, pending, and abstained outputs remain in the declared scoring denominator. The ASA label `undetermined` is a substantive rubric prediction, not an operational abstention.

## Standardization decisions

See `STANDARDIZATION.md` for exact field mappings. The common `example_id` and `status` interface remains compatible with the earlier kit. Existing three-dataset adapters and scoring semantics are preserved.

ASA `claim_id` becomes the same-string `example_id` while remaining available as native provenance. Enum spellings are normalized to lowercase; source spellings remain in native references. Native ruling outcomes such as `Upheld in part` are **not** mapped to binary truth or overstatement labels.

Several ASA records reuse a ruling-summary ID for different assertion-specific text. Corpus IDs are therefore namespaced as `<claim_id>:<native_document_id>`. This avoids overwriting or conflating summaries. The native document ID and URL are retained for attribution and round-trip exports.

Dates retain their source precision, and unknown dates stay null. Ruling dates are used only as supplied retrospective cutoffs. No earlier evidence-availability claim is introduced.

## Scoring and review

ASA results are explicitly tagged `PROVISIONAL_DRAFT_COMPARISON_NOT_BENCHMARK_RESULT`. Metrics include material-label and evidence-status accuracy, macro-F1, joint accuracy, confusion matrices, prediction coverage, false adverse findings on absent references, company-macro accuracy, and optional multiclass Brier/log loss. Matching a supplied citation ID is only a locator diagnostic; explanation quality, citation entailment, and supported-rewrite quality remain ungraded without human review.

The shared scorer retains missing cases in its denominator. This differs from the original ASA scorer's explicit partial mode, which reports accuracy on supplied predictions. Full-coverage common metrics can be cross-checked through native export; do not compare differently selected denominators.

```bash
python benchmark.py review-sheet --dataset asa --mode retrospective --predictions outputs/asa.predictions.jsonl --output outputs/asa.review.csv
```

The generated review sheet is reference-bearing. Reviewer and adjudication fields remain blank. Editing a CSV does not automatically promote draft references, establish evidence sufficiency, or unlock independent scoring. Further curation and a versioned import protocol are still needed for independent evaluation.

Native interoperability:

```bash
python benchmark.py import-predictions --dataset asa --mode retrospective --predictions native_predictions.jsonl --output outputs/asa.normalized.jsonl
python benchmark.py native-export --dataset asa --mode retrospective --predictions outputs/asa.normalized.jsonl --output outputs/asa.native
```

The importer maps PascalCase labels and native evidence IDs to the shared format. Null template labels remain pending. Native export requires all selected predictions completed; it will not silently drop failures. There is no official ASA benchmark scorer. `official-export` remains reserved for the original FinQA/AVeriTeC integrations.

## Experimental scope

This is a diagnostic collection, not a balanced population sample, held-out official test, or complete archive. Keep related assertions from a company/campaign together when constructing future splits; no train/dev/test split is invented here. Existing public material can be memorized by models, and reconstructed claim excerpts omit original visual presentation. Retrospective agreement cannot establish early detection, intent, deployment prevalence, or calibrated public allegation probabilities.

See `VALIDATION_REPORT.md` for exactly what ran. Tests and draft-identity checks verify software plumbing, not the correctness of the source compiler's interpretations. ASA's original workbook, notices, prompts, and source registers remain unchanged inside the preserved source archive. This kit is not created or endorsed by ASA.
