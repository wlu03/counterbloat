# Countercheck

Countercheck reads a corporate document, extracts its substantive claims, and checks whether the
wording of each claim is justified by the evidence it can find. For each claim it reports the
evidence status, the specific discrepancy, the calculation, a wording the evidence supports, and
what remains unresolved. It does not infer intent and it does not publish a probability.

## Run

    docker compose up -d            # PostgreSQL and Elasticsearch
    cp .env.example .env            # fill in keys and model identifiers
    uv sync
    uv run --env-file .env uvicorn backend.api.app:app --reload   # the app does not read .env itself
    cd apps/web && npm install && npm run dev

Without `DATABASE_URL` the backend uses a local SQLite file. Without `ELASTICSEARCH_URL` it uses an
in-memory keyword index. Jev routing and Token Company compression are optional. When a key is
missing the step is skipped and nothing is recorded. When a call fails, the passage is extracted
without routing, or the context is sent uncompressed, and the error is added to the run manifest.

## Test

    uv run pytest

Tests use fake providers and need no keys or services.

## Updating strategies and experiments

`assessment.updater` in `config/app.yaml` selects `linguistic`, `full_context`, or
`evidence_accumulator`. `docs/belief_updating.md` states what each one computes. Internal scores
are experimental and uncalibrated. A finding never has a probability. Set
`COUNTERCHECK_RESEARCH_VIEW=1` to let the reader show the internal research panel.

    uv run python -m evaluation.replay.run --trace evaluation/fixtures/emissions.json --out results/replay_emissions.json
    uv run python -m evaluation.report results --out results/report.md

`docs/evaluation_protocol.md` lists the commands for dataset preparation, the baseline and
pipeline runs, the ablations, and the budgeted live smoke test.
