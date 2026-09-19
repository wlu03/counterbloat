# AVeriTeC test guide

## Scope and split

Prepare the **500 FEVER-7 development examples** as a local labeled evaluation set. This is **not** the official blind test or the newer FEVER-8 release. The claim data, evidence collection, and scorer are pinned to one matched FEVER-7 mirror linked by the official FEVER dataset page.

Use native labels: `Supported`, `Refuted`, `Not Enough Evidence`, and `Conflicting Evidence/Cherrypicking`. Missing evidence is not refutation. These labels assess general claims, not broad corporate overstatement or deceptive intent. The source terms are **CC BY-NC 4.0**, with separate rights for underlying documents.

## Prepare the small claim/reference files

```bash
python -m datasets.benchmark prepare --dataset averitec --accept-license
python -m datasets.benchmark validate --dataset averitec
```

The original zero-based dev row order is preserved as `claim_id`, with IDs such as `averitec-dev-0000`. Never renumber a subset: the knowledge-store mapping uses the original indices. The downloader checks the expected count and records hashes. It has not run in the authoring session.

The model receives the claim and permitted metadata. Native verdicts, justifications, annotated QA, claim types, fact-checking strategies, and answer-bearing fact-checking URLs remain evaluator-only.

## Full retrieval corpus: explicit large download

```bash
# Print the planned URL and size, without downloading the archive.
python -m datasets.benchmark corpus --dataset averitec --accept-license

# Approximately 11.5 GB download plus extraction space.
python -m datasets.benchmark corpus --dataset averitec --accept-license --confirm-large-download --extract
```

The published SHA256 is checked. Interrupted downloads support resumption where the server supports ranges. JSON/JSONL archive extraction is path-safe; pickle/model files are never deserialized. A corpus manifest is written after successful completion.

**This is source download/extraction, not an Elasticsearch importer.** Inspect the raw per-claim JSON and map each file to its original `claim_id` when implementing retrieval. Preserve dates, source URLs, and provenance; do not index all answer keys. The corpus is not certified free of answer-bearing fact checks, duplications, or historical leakage. These claims are general verification examples, not guaranteed pre-exposure corporate cases.

## Run your actual investigator

Implement `my_adapter:predict`. Native output example (format only, not a verdict on an actual dataset row):

```json
{"example_id":"ID_FROM_INPUT","status":"ok","label":"Not Enough Evidence","evidence":[{"question":"A verification question","answer":"The source-grounded answer","url":"https://example.org/source"}]}
```

```bash
python -m datasets.benchmark select --dataset averitec --count 25 --output pilot.ids.json
python -m datasets.benchmark run --dataset averitec --ids pilot.ids.json --adapter my_adapter:predict --output pilot.predictions.jsonl
python -m datasets.benchmark score --dataset averitec --ids pilot.ids.json --predictions pilot.predictions.jsonl --output pilot.verdict_scores.json
```

Omit `--ids` to evaluate all 500 after freezing prompts and settings. The included abstaining adapter only checks wiring. Do not train/calibrate on this holdout and continue calling it untouched.

## Local diagnostic versus official evidence-conditioned scoring

The stdlib local scorer provides verdict accuracy, macro-F1, confusion matrix, insufficient-to-refuted errors, and optional four-class Brier/log loss with probability coverage. **It does not calculate the official evidence-conditioned AVeriTeC score.**

For that score:

```bash
python -m pip install -r requirements-evaluation.txt
python -m nltk.downloader punkt punkt_tab wordnet omw-1.4
python -m datasets.benchmark official-export --dataset averitec --predictions pilot.predictions.jsonl --ids pilot.ids.json --output official_averitec
```

Run the exact command in `official_averitec/COMMAND.txt`. It calls the downloaded, pinned original evaluation script. Native reference rows are aligned in the same order as exported predictions; absent outputs remain in the denominator. The export uses an empty QA placeholder for missing evidence to avoid empty-array problems in older matching code. That placeholder is not evidence.

Official automatic evidence matching is a proxy. Valid alternative evidence may not match the reference; review a sample of cited conclusions. Upstream scorer execution and live corpus runs were not performed here.

## Oracle interpretation test

```bash
python -m datasets.benchmark oracle --dataset averitec --acknowledge-oracle --output oracle/averitec.inputs.jsonl
```

This supplies the annotated questions/answers and therefore some human decomposition. Use a separate oracle-aware caller: the default `run` command intentionally reads only normal runtime inputs. Clearly label these as oracle-evidence results, not independent evidence retrieval.
