# Counterbloat public benchmark download-and-test kit

**This ZIP contains runnable preparation/evaluation tools, not preloaded benchmark data.**
Direct downloads into the authoring session failed. Run `prepare` on a machine with internet access to fetch the original release and build the test files. No full dataset download, public benchmark evaluation, or live model run was completed while creating this kit.

The three supported tasks are different:

| Dataset | Requested evaluation collection | Task |
|---|---|---|
| FinQA | 1,147 labeled public-test examples | Financial numerical reasoning |
| FinanceBench | 150 public examples | Question answering over financial reports |
| AVeriTeC | 500 FEVER-7 development examples | General claim verification with evidence |

These are expected source counts checked by preparation, **not counts already included in the ZIP**. AVeriTeC's accessible labeled development split is used for local testing; it is not an official blind test. FinanceBench's public sample has no separate official held-out split in this package. None of these alone measures accuracy on corporate claim overstatement.

## Start

Python **3.10+** is required. Unzip, open a terminal in the extracted directory, and run:

```bash
python -m venv .venv
source .venv/bin/activate
python -m unittest discover -s tests -v
```

Windows activation: `.venv\Scripts\Activate.ps1`. On systems where `python` is not installed as a command, use `python3`.

The standalone ZIPs select their own dataset. The combined ZIP requires `--dataset finqa`, `--dataset financebench`, or `--dataset averitec` on each command. Read `THIRD_PARTY_NOTICES.md` before accepting the dataset terms.

```bash
# Example using the combined kit; omit --dataset in the matching standalone kit.
python benchmark.py prepare --dataset finqa --accept-license
python benchmark.py validate --dataset finqa
python benchmark.py template --dataset finqa --output predictions.finqa.jsonl
```

`prepare` downloads a commit-pinned release, applies an input allowlist, checks row count and unique IDs, and records SHA256 hashes. Known Git blob hashes additionally check the two GitHub data files. AVeriTeC's full corpus has a published SHA256. Ancillary download failures are recorded, never silently reported as success.

If you already downloaded the pinned source, use `--input-file /path/to/test.json` (or the relevant JSONL/dev file). FinanceBench also supports `--metadata-file`. Metadata and upstream scorers may still need internet access. Do not use another release with the pinned adapters without reviewing its schema, counts, and evaluation protocol.

## Generated files

```text
data/<dataset>/
  manifest.json                         # Source revision, downloads, counts, SHA256s
  corpus_manifest.json                  # Only after a corpus download
  runtime/
    inputs.jsonl                        # Model-visible allowlisted inputs
    metadata.json
    corpus/                             # FinQA excerpts, report metadata, or source corpus
  evaluator_only/
    references.jsonl                    # Gold answers/labels/evidence
    native_references.json              # Original rows for official evaluators
    upstream/                           # Original data, upstream scorer, attribution
  downloads/                            # Large archive/tree downloads when requested
```

**Do not index the whole `data/` folder.** The original rows contain answers. Give the inference worker only `runtime/`. Separate folders are an interface boundary, not OS-level isolation. Use `export-runtime` to create a shareable runtime-only ZIP and mount it in a separate worker/container:

```bash
python benchmark.py export-runtime --dataset finqa --output finqa_runtime_only.zip
```

`validate` checks exact allowed input keys, counts, ID alignment, and prepared-file checksums. It cannot prove the source text contains no indirect answer cues or that a model has never seen a public benchmark.

## Connect the actual system

This kit does not modify your repository and does not invent a Counterbloat API endpoint. Implement one Python function in `my_adapter.py`:

```python
from pathlib import Path

def predict(example: dict, runtime_dir: Path) -> dict:
    # Call your actual system, retrieving only from runtime_dir/corpus.
    # Return the native prediction shape shown in PREDICTION_FORMAT.md.
    ...
```

Then run:

```bash
python benchmark.py run --dataset finqa --adapter my_adapter:predict --output predictions.finqa.jsonl
```

The runner passes a copy of the allowlisted example and the runtime directory; it does not read references. Python adapters are trusted code, not sandboxed: enforce filesystem isolation separately. Any API calls and costs are your adapter's responsibility. Return model/provider versions and usage metadata in predictions when available.

`example_adapter.py` deliberately abstains. It is only an integration template, not a baseline model. Templates use `status="pending"`; filling a file with templates does not count as completed inference. Failed/absent predictions remain in the evaluation denominator. Existing prediction files are not overwritten.

## Small, declared pilot

Choose a subset **before observing predictions**:

```bash
python benchmark.py select --dataset finqa --count 25 --seed 20260919 --output pilot.ids.json
python benchmark.py run --dataset finqa --ids pilot.ids.json --adapter my_adapter:predict --output pilot.predictions.jsonl
python benchmark.py score --dataset finqa --ids pilot.ids.json --predictions pilot.predictions.jsonl --output pilot.scores.json
```

Selection hashes seed + ID; it does not read labels. This is a pilot subset, not the full benchmark. Use the same ID file when comparing configurations and scoring. Do not tune on the final holdout. The package does not create training examples or calibration splits from test data.

## Scoring

FinQA's primary local scorer calls the downloaded official `eval_program`, preserving its numeric execution semantics and using the full declared denominator. Program-equivalence accuracy is not implemented in the local summary; the official export supports the original full evaluator. `--answer-only` is an explicitly named nonofficial numeric diagnostic for systems returning only a scalar.

AVeriTeC's dependency-free local scorer reports native verdict accuracy, macro-F1, a confusion matrix, missing-evidence-to-refutation errors, and optional probability metrics. **It is not the official evidence-conditioned AVeriTeC score.** Use `official-export` plus the pinned upstream scorer for that result.

FinanceBench requires semantic correctness review. Automatic string equality is labeled a diagnostic, not answer accuracy. The kit generates a reference-bearing review CSV; after human review, it computes answer and evidence-backed accuracy. Matching a reference page is not proof that a citation supports the conclusion.

Read the dataset-specific guide before running scoring commands: `guides/FINQA.md`, `guides/FINANCEBENCH.md`, or `guides/AVERITEC.md`.

## Corpus options

FinQA's released full text/table excerpts are prepared immediately; no full-report PDFs are needed for this native task.

FinanceBench report metadata are prepared immediately. The full PDF collection is downloaded separately, with size/file-count preview and explicit opt-in. Optional page text extraction uses PyMuPDF; original PDFs remain authoritative for table layout.

AVeriTeC's question/label files are prepared immediately. Its approximately **11.5 GB** FEVER-7 development knowledge-store archive is an explicit separate download. JSON extraction is optional and path-safe. **The importer does not index that corpus into Elasticsearch.** Keep the upstream per-claim file mapping and inspect its records before indexing. It does not deserialize pickle files or download models.

```bash
# Plan first; this does not fetch the large PDFs/archive.
python benchmark.py corpus --dataset financebench --accept-license
python benchmark.py corpus --dataset averitec --accept-license

# Explicit large download; optional extraction.
python -m pip install -r requirements-corpus.txt
python benchmark.py corpus --dataset financebench --accept-license --confirm-large-download --extract
python benchmark.py corpus --dataset averitec --accept-license --confirm-large-download --extract
```

For AVeriTeC, allow space for the archive and extracted files. The JSON extractor has a 120 GiB uncompressed cap and skips non-JSON files. A recorded failure is not an empty or complete corpus. Review the source collection for answer-bearing fact checks and known duplications; runtime field allowlisting does not sanitize arbitrary retrieved documents. These downloads do not establish historical source availability.

## Optional oracle evidence

Oracle mode supplies annotated evidence, so it tests interpretation, not evidence discovery:

```bash
python benchmark.py oracle --dataset financebench --acknowledge-oracle --output oracle/financebench.inputs.jsonl
python benchmark.py oracle --dataset averitec --acknowledge-oracle --output oracle/averitec.inputs.jsonl
```

Oracle output is explicitly marked and cannot be written under `runtime/`. The default runner always reads normal runtime inputs; use a separate oracle-aware caller for these exported files. Do not merge them into a retrieval index or report their results as independent retrieval.

## What was tested here

See `VALIDATION_REPORT.md`. Offline unit tests and synthetic command-line smoke tests validate adapters, ID handling, local metrics, mock downloads, and isolation checks. These are not public-dataset runs. Network downloads, complete dataset schemas, real PDF corpus extraction, and upstream scorer execution must be validated on your machine after preparation.
