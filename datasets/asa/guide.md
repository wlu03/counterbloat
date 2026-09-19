# ASA test-kit guide

## What can be run immediately

The included normalized retrospective packet has 30 assertions and 30 short, answer-bearing compiler summaries derived from 24 rulings. It supports **retrospective interpretation**. All reference labels are unreviewed compiler drafts. ASA did not author or endorse this test pack.

```bash
python -m datasets.benchmark validate --dataset asa --mode retrospective
python -m datasets.benchmark run --dataset asa --mode retrospective --adapter my_adapter:predict --output outputs/asa.predictions.jsonl
python -m datasets.benchmark score --dataset asa --mode retrospective --allow-draft --predictions outputs/asa.predictions.jsonl --output outputs/asa.metrics.json
```

The original three benchmark commands are unchanged. Always pass `--dataset asa` and `--mode`.

## Input / model request

Read `runtime/inputs.jsonl`. For each example, select only records from `runtime/corpus/passages.jsonl` with its `example_id` and an ID in `allowed_evidence_ids`. Never retrieve another case's summary as evidence for this claim. `../benchkit/example_asa_adapter.py`'s `build_request` implements this filtering.

Your model instruction should clearly say that a supplied assessment summary contains answer-bearing information. Ask it to interpret that summary and the claim's scope, not pretend to independently investigate the allegation. Do not give it compiler draft labels or the reference workbook.

Use `prompt_retrospective.txt` as a task instruction. Return the normalized output contract in `../benchkit/PREDICTION_FORMAT.md`. A program should not add raw summary text as an additional independent observation when it also retrieves the underlying ruling.

## Evidence and target semantics

`material_overstatement` is a project-rubric label: `present`, `absent`, or `undetermined`. `evidence_status` is independently `supported`, `contradicted`, `mixed`, `insufficient`, or `not_yet_resolvable`. Do not map `Upheld` directly to `present`, nor treat insufficient evidence as contradiction. The compiler's absent label is limited to the selected assertion and context, not the company as a whole.

The supplied per-case summaries are not full rulings, original ads, source studies, or frozen contemporaneous evidence. Source URLs/date/locators remain attached for attribution. No page capture, citation entailment verification, or new source retrieval was performed while integrating the package.

## Independent candidates

```bash
python -m datasets.benchmark validate --dataset asa --mode independent
python -m datasets.benchmark export-runtime --dataset asa --mode independent --output outputs/asa.independent.candidates.zip
```

This is an ingestion/curation packet only. All 30 cases lack admitted independent evidence and adjudicated references. `run` and `score` in independent mode refuse to proceed; `--allow-draft` cannot bypass this. Changing a readiness flag alone is insufficient. Independent evaluation needs original-context capture, explicit cutoffs, admissible evidence, and evidence-conditioned review in a new versioned dataset. This integration does not fabricate those missing materials.

## Reusing outputs from the original ASA pack

```bash
python -m datasets.benchmark import-predictions --dataset asa --mode retrospective --predictions native_predictions.jsonl --output outputs/asa.normalized.jsonl
python -m datasets.benchmark native-export --dataset asa --mode retrospective --predictions outputs/asa.normalized.jsonl --output outputs/asa.native
```

Native exports can be scored using the original `scripts/score.py` in the upstream pack, which is not included here. Supply exported `references.jsonl`, `--mode retrospective`, and `--allow-draft`. This is the compiler's local scorer, not an official ASA benchmark. A native export requires completed predictions for every selected row.

## Small runs

```bash
python -m datasets.benchmark select --dataset asa --mode retrospective --count 5 --seed 20260919 --output outputs/asa.pilot.ids.json
python -m datasets.benchmark run --dataset asa --mode retrospective --ids outputs/asa.pilot.ids.json --adapter my_adapter:predict --output outputs/asa.pilot.predictions.jsonl
python -m datasets.benchmark score --dataset asa --mode retrospective --allow-draft --ids outputs/asa.pilot.ids.json --predictions outputs/asa.pilot.predictions.jsonl --output outputs/asa.pilot.metrics.json
```

Selection is ID-hash based without reading labels. It is a diagnostic subset, **not** a new train/test split. For future group-disjoint testing use `evaluator_only/id_mapping.jsonl`; do not treat the 30 assertions as 30 independent companies.

## Review

`review-sheet` produces a reference-bearing CSV with model outputs, claim context, company/campaign grouping, two reviewer columns, adjudication columns, and explanation/citation/rewrite checks. Reviewer fields start blank. Automatic import of adjudications or promotion to independent-ready is not implemented.

Optional probabilities estimate the three material-overstatement rubric classes, not intent. Draft-label Brier score is a provisional agreement diagnostic; it does not validate public confidence displays. Retain raw model outputs, model/prompt versions, source corpus hashes, and error status when comparing configurations.
