# FinQA test guide

## Scope

Prepare the **1,147 labeled public-test examples** from the commit pinned in `../benchkit/sources.py`. These are the expected downloaded rows, not data bundled here. Do not substitute the private unlabeled test. The native task is numerical question answering over supplied financial text and tables, not detecting misleading companies.

## Download and prepare

```bash
python -m datasets.benchmark prepare --dataset finqa --accept-license
python -m datasets.benchmark validate --dataset finqa
python -m pip install -r requirements-evaluation.txt
```

Read `../benchkit/THIRD_PARTY_NOTICES.md` before accepting terms. Dataset preparation itself uses only the Python standard library. Scoring programs uses the original downloaded evaluator and its dependencies. The data Git blob hash and downloaded file SHA256 are checked/recorded. A failed scorer download is recorded in the preparation manifest and blocks program scoring until resolved.

## What the model receives

`runtime/inputs.jsonl` supplies only the ID, question, `pre_text`, `post_text`, and `table` plus task metadata. `runtime/corpus/excerpts.jsonl` contains uniformly serialized text/table chunks. They represent the released excerpt, not the entire company report.

Keep `evaluator_only/` inaccessible to inference. It holds the answer, execution result, gold program, supporting annotations, and original answer-bearing rows. Never use `gold_inds` or preselected `model_input` as a retrieval input in an end-to-end run.

## Run a pilot, then the full split

Implement `my_adapter:predict` as described in `../benchkit/README.md` and `../benchkit/PREDICTION_FORMAT.md`. Return a native token program, for example a **synthetic formatting example**:

```json
{"example_id":"ID_FROM_INPUT","status":"ok","predicted_program":["divide(","10","100",")","EOF"],"evidence_ids":["table_1"]}
```

```bash
python -m datasets.benchmark select --dataset finqa --count 25 --output pilot.ids.json
python -m datasets.benchmark run --dataset finqa --ids pilot.ids.json --adapter my_adapter:predict --output pilot.predictions.jsonl
python -m datasets.benchmark score --dataset finqa --ids pilot.ids.json --predictions pilot.predictions.jsonl --output pilot.scores.json

# Full public test: omit --ids, and use new output names.
python -m datasets.benchmark run --dataset finqa --adapter my_adapter:predict --output finqa.predictions.jsonl
python -m datasets.benchmark score --dataset finqa --predictions finqa.predictions.jsonl --output finqa.scores.json
```

The shipped `datasets.benchkit.example_adapter:predict` deliberately abstains. It verifies wiring, not model performance. Pilot examples are test examples: do not tune on the pilot and then call the whole set untouched. For development, obtain the official training/development split separately.

## Interpret the metrics

The primary local score executes the published program with the pinned `eval_program` and compares the original `exe_ans`. Missing/failed predictions remain in the denominator. It does not automatically establish that each operand came from the correct source row.

For an answer-only system:

```bash
python -m datasets.benchmark score --dataset finqa --predictions finqa.predictions.jsonl --answer-only --output answer_only.json
```

That score is a **nonofficial scalar diagnostic**, not program-execution or program-equivalence accuracy. Use a scalar or yes/no; `10%` is parsed as `0.1`, not `10`. Prose is not searched opportunistically for a convenient number.

For the original full evaluator, including its program-equivalence metric:

```bash
python -m datasets.benchmark official-export --dataset finqa --predictions finqa.predictions.jsonl --output official_finqa
```

Run the exact command saved in `official_finqa/COMMAND.txt`. The exporter aligns references to the declared selection and fills absent predictions rather than dropping them. Official evaluator execution was not run in the authoring environment.
