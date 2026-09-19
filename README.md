# Countercheck

Countercheck reads a corporate document, extracts its substantive claims, and checks whether the
wording of each claim is justified by the evidence it can find. For each claim it reports the
evidence status, the specific discrepancy, the calculation, a wording the evidence supports, and
what remains unresolved. It does not infer intent and it does not publish a probability.

## Run

    docker compose up -d            # PostgreSQL and Elasticsearch
    cp .env.example .env            # fill in keys and model identifiers
    uv sync
    uv run uvicorn backend.api.app:app --reload
    cd apps/web && npm install && npm run dev

Without `DATABASE_URL` the backend uses a local SQLite file. Without `ELASTICSEARCH_URL` it uses an
in-memory keyword index. Jev routing and Token Company compression are optional; when a key is
missing or a call fails, the unoptimized path runs and the run manifest records it.

## Test

    uv run pytest

Tests use fake providers and need no keys or services.
