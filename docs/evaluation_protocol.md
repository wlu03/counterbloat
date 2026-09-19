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
saved in the trace. It checks ordering, duplicates, irrelevant additions, corrections, and
withdrawals without any paid call. The seed (default 7) is written to the result.

To replay a stored investigation, export it first:

    uv run python -m evaluation.replay.trace ANALYSIS_ID CLAIM_ID --out results/trace.json

To replay with the real models, which is paid and bounded by `--max-calls`:

    uv run --env-file .env python -m evaluation.replay.run --trace results/trace.json \
        --provider openai --permutations 1 --max-calls 120 --out results/replay_live.json

## Budgeted live smoke test

    uv run --env-file .env python -m evaluation.smoke --max-calls 25 --out results/smoke.json

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
        --system A1 --limit 20 --max-calls 200 --out results/averitec_A1.jsonl
    uv run --env-file .env python -m evaluation.experiments.run verify --dataset averitec \
        --visible prepared/averitec/dev.visible.jsonl --searchable SEARCHABLE.jsonl \
        --system A2 --updater evidence_accumulator --limit 20 --max-calls 600 \
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

## Report

    uv run python -m evaluation.report results --out results/report.md

The report lists every replay result and every scored run found in the directory. A value that
was not produced is written as unavailable.

## Rules

Keep demo cases out of any test set. Lock the configuration before scoring a test set. Do not
relabel a dataset as overstatement labels. Selective error is undefined when no case is accepted.
