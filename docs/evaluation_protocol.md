# Evaluation protocol

No dataset experiment has been run. The commands below exist. All except the live smoke test
are covered by tests that use scripted providers. The results produced so far are the scripted
replays of the two synthetic fixtures and two live smoke runs of the fictional example.

## Deterministic suite

    uv run pytest

No keys, services, or network. It covers the arithmetic of the fictional emissions example, the
order of calculation and update, the link between a calculation and the claim, duplicate
groups and duplicate events, retries, corrections, withdrawals, merges, removed sole support,
missing and unusable scores, compression damage, provider failure, review changes and follow-up,
the historical cutoff, label isolation, and the null public probability.

## Fixed-evidence replay of the three strategies

    uv run python -m evaluation.replay.run --trace evaluation/fixtures/mechanics.json \
        --prior 0.2 --out results/replay_mechanics.json
    uv run python -m evaluation.replay.run --trace evaluation/fixtures/emissions.json \
        --out results/replay_emissions.json

The default provider is scripted: the status follows a fixed rule and the scores are the ones
saved in the trace. A saved score applies only to the source groups, relations, and calculations
it was recorded for. In any other context the scripted provider abstains, and the abstention is
listed in the run's errors. Every question starts open, and a saved answer is applied once the
evidence it cites has been admitted. A run in which a provider call failed or was refused by
the budget is marked incomplete and is reported as not run. It checks ordering, duplicates, irrelevant additions, corrections, and
withdrawals without any paid call. The seed (default 7) is written to the result.

To replay a stored investigation, export it first:

    uv run python -m evaluation.replay.trace ANALYSIS_ID CLAIM_ID --out results/trace.json

The paid commands below run with high default bounds: `--max-calls` is 5000 for a replay, 500
for the smoke test, and 50000 for a dataset run, and `--limit` is 2000 examples. Pass a smaller
value to cap the spend of a run.

To replay with the real models, which is paid and bounded by `--max-calls`:

    uv run --env-file .env python -m evaluation.replay.run --trace results/trace.json \
        --provider openai --permutations 1 --out results/replay_live.json

## Budgeted live smoke test

    uv run --env-file .env python -m evaluation.smoke --out results/smoke.json

One run of the fictional emissions report through the real providers with the accumulator. The
command exits with an error if no finding is produced or if a finding has a public probability.
No test covers this command.

## Dataset preparation

    uv run python -m datasets.prepare averitec PATH/TO/LOCAL/FILE.json --revision REVISION --split dev

The file must already be on disk. Nothing is downloaded. Obtain each dataset from its publisher
under its license. The command writes `prepared/DATASET/SPLIT.visible.jsonl` (runtime inputs),
`gold/DATASET/SPLIT.jsonl` (labels, owner-readable only), and `prepared/DATASET/SPLIT.manifest.json`
with the file hash, row count, revision, license, and field names. `prepared/`, `gold/`, and `results/` are ignored by
git.

A system under test reads three things and nothing else: the visible file, the searchable file,
and its own store. The searchable file is supplied by the user, one row per document:
`{"example_id", "content", "media_type"?, "url"?, "published_at"?}`. Each example gets a fresh
store and index that hold only its own searchable documents. The gold file is opened by the
`score` command only.

Datasets keep their own labels. environmental_claims measures claim detection. AVeriTeC measures
agreement between the evidence status and the dataset verdict, and its scoring target is the
dataset's Refuted label, not overstatement.

## Baseline against the structured pipeline

    uv run --env-file .env python -m evaluation.experiments.run verify --dataset averitec \
        --visible prepared/averitec/dev.visible.jsonl --searchable SEARCHABLE.jsonl \
        --system A1 --out results/averitec_A1.jsonl
    uv run --env-file .env python -m evaluation.experiments.run verify --dataset averitec \
        --visible prepared/averitec/dev.visible.jsonl --searchable SEARCHABLE.jsonl \
        --system A2 --updater evidence_accumulator \
        --out results/averitec_A2.jsonl
    uv run python -m evaluation.experiments.run score --dataset averitec \
        --predictions results/averitec_A2.jsonl --gold gold/averitec/dev.jsonl \
        --prices PRICES.json --out results/averitec_A2.score.json

A1 is one search on the claim text and one judgment. A2 is the structured pipeline. Both use the
same searchable documents and the same in-memory keyword index, and each prediction that made a
search records that no vector search took place. An example in which a provider call failed or
was refused by the call budget is written as `not_run` and is left out of the score, as are
examples after the budget is used up. Gold rows without a usable label are counted and skipped. Brier score and negative log-likelihood cover only the examples that
have a score, and are `unavailable` when none has or when the predictions name different
targets. Cost is `unknown` unless the price list names every model that was used, and also
whenever Jev or Token Company calls were made, because their prices are not modelled.

## Jev and compression ablations

    ... verify --system A3    # Jev routing
    ... verify --system A4    # protected compression
    ... verify --system A5    # both
    uv run --env-file .env python -m evaluation.experiments.run detect \
        --visible prepared/environmental_claims/test.visible.jsonl --jev --out results/detect_jev.jsonl

Each prediction records calls by provider and purpose, failed calls, tokens by model, latency,
passages excluded by the router, and compression fallbacks. For a compression comparison, use
the same searchable file for both systems so that retrieval is the same.

## Comparison with single-prompt systems

    uv run --env-file .env python -m evaluation.comparison.run --out results/comparison.json
    uv run --env-file .env python -m evaluation.comparison.run --arms pipeline chatgpt \
        --repeats 3 --out results/comparison_repeats.json

Three arms audit the same cases:

- `pipeline`: the structured investigation in this repository.
- `chatgpt`: one call to the same OpenAI reasoning model, at the same reasoning effort, with the
  prompt in `evaluation/comparison/schema.py`. It has no tools and no browsing, because every
  case supplies its documents.
- `devin`: one Devin session per case through the v3 API with the same prompt, a required
  structured output, and an ACU limit per session (`--devin-max-acu`, default 5). It needs
  `DEVIN_API_KEY` (a service-user key, prefix `cog_`) and `DEVIN_ORG_ID` (`org-...`). Without
  both, the arm is reported as not run.

Conditions that are the same for every arm: the passages, which are parsed once by this
repository's parser and given with their document ids, and the output format. The two
single-prompt arms get the status definitions and the rules (exact quotes, arithmetic, no
probability) in their prompt. The pipeline does not get that prompt: its own prompts name the
statuses, and its rules are enforced in code. It runs with `config/evaluation.yaml`: frozen mode,
two investigation rounds, one follow-up round, no Jev routing, no compression. No arm is given a case's
expected answer. The cases are synthetic, use fictional companies, and supply all their
documents, so retrieval from the web is not compared.

`evaluation/comparison/cases.json` holds the cases. Each was written with an expected status and
was kept only if three solvers, who were not shown the expected answer, each gave an accepted
status and at least two of them reached every key number.

The scorer is code. Per case it records whether the claim was found (the finding whose quote
covers most of the expected claim text), whether the status is one of the accepted ones, whether
each key number was calculated, how many evidence quotes are exact
substrings of a supplied passage, which numbers in the summary or rewrite appear in no passage
and in no reference calculation (listed, not judged, because they can be correct arithmetic),
whether a probability was stated, and how many other findings were returned. With `--repeats`
above 1 it records the share of cases that got the same status in every repeat. Cost is reported
as OpenAI calls and tokens, Devin sessions and ACUs, and seconds, and it includes runs that
failed. A key number counts when it is among the calculated values, where a share given as a
fraction of 1 counts as its percentage. In the summary or rewrite it counts only when the
documents do not contain that number, because restating the claim is not a calculation.

Two kinds of failure are kept apart. A system that ran and gave no usable answer (the pipeline
job failed, or a Devin session timed out, ended without structured output, or returned another
format) is scored as a miss. A system that could not be run (an outage, a missing key, the call
budget) is counted and left out of that arm's rates. A pipeline run in which one provider call
failed is scored as returned and counted as a partial run. A Devin session that times out is
stopped through the API.

`--reuse EARLIER.json` takes the arms that are not run now from an earlier result and scores
their stored outputs again, so the Devin arm can be added later and a scorer change needs no
new paid run.

Limits of this comparison: the cases are small and synthetic, the passages come from this
repository's parser, the prompt for the other two arms was written here, and the pipeline's own
rules (exact quotes, the number rule) match what the scorer checks. A result on these cases says
how the systems behave on this kind of input. It is not a measurement on real disclosures.

### Results so far (2026-09-19)

One run per case, models `gpt-5.6-luna` (extraction) and `gpt-5.6-sol` (reasoning) at low
reasoning effort, pipeline updater `linguistic`. The Devin arm has not run: `DEVIN_ORG_ID` is not
set. The result files are in `results/`, which git ignores.

| | single OpenAI prompt | pipeline, first run | pipeline, second run | pipeline, third run |
|---|---|---|---|---|
| commit | 4e87684 | 4bcc994 | 6762656 | abbdd24 |
| status correct | 15 of 15 | 8 of 15 | 9 of 15 | 14 of 15 |
| key numbers calculated | 9 of 9 | not rescored | 4 of 9 | 8 of 9 |
| exact quotes | all | all | all | all |
| findings with no quote | 2 | 0 | 0 | 0 |
| findings other than the case's claim | 47 | 2 | 3 | 5 |
| OpenAI calls | 15 | 144 | 175 | 193 |
| tokens in / out | 22,620 / 17,672 | 410,233 / 98,331 | 476,943 / 119,130 | 552,829 / 126,677 |
| seconds | 200 | 1,676 | 1,648 | 1,863 |

What the three pipeline runs showed:

- First run: the job failed on three cases with `KeyError` in the group lookup. One quote
  admitted for two targets in one round was not handled. The defect came in with commit
  `37e01bf`, and no test covered that path. In the table those three cases count as wrong.
- Second run: five cases ended `insufficient` because the calculator rejected a sum of parts
  with different populations, such as plants or regions added to a company total. The calculator
  also had no operation for a percentage share. Both are fixed, with tests.
- Third run: one case is wrong. The updater proposed `mixed`, the review objected that the
  evidence supports the claim as worded, and a review rejection can only produce
  `insufficient`. A correct objection by the review therefore gave a wrong status. This is a
  limit of the design, not of these cases, and it is not changed here.

How to read this:

- On these cases the single prompt is as accurate as the pipeline or more accurate, at about
  one thirteenth of the calls and one ninth of the time. These cases supply every document and
  need at most a few steps of arithmetic. They do not test retrieval from a large corpus, long
  documents, evidence that changes over time, or repeated runs.
- The single prompt returned 47 findings about sentences other than the case's claim, which are
  background facts it was told to skip, and 2 findings with no quote. The pipeline returned 5 and
  0. Nothing in the prompt arm checks a quote or a number in code: on these cases the model
  complied, and nothing would have stopped it if it had not.
- After the first run, the pipeline was changed in response to failures on these cases. The 15
  cases are therefore development data for the pipeline and no longer a held-out test. The
  single-prompt arm was run once and not changed.
- One run per case does not measure run-to-run variation. The pipeline gave `mixed` and then
  `insufficient` for the same case in two runs. Use `--repeats 3` for that measure.

## Report

    uv run python -m evaluation.report results --out results/report.md

The report lists every replay result and every scored run found in the directory. A value that
was not produced is written as unavailable.

## Rules

Keep demo cases out of any test set. Lock the configuration before scoring a test set. Do not
relabel a dataset as overstatement labels. Selective error is undefined when no case is accepted.
