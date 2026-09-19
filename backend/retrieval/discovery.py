"""External source discovery for live mode. A search result is accepted only after fetching it."""
from __future__ import annotations

from backend.db import Store
from backend.ingestion.fetch import BlockedDestination, FetchError
from backend.ingestion.snapshot import admit_url
from backend.models import Mode, RunManifest
from backend.providers.base import LLM, ProviderError
from backend.retrieval.search import SearchIndex

MAX_SOURCES = 3


def discover(llm: LLM, store: Store, index: SearchIndex, query: str, mode: Mode,
             manifest: RunManifest) -> list[str]:
    """Fetch, preserve, and index candidate sources. Return the new document ids."""
    if mode != Mode.live:
        return []
    try:
        urls = llm.discover(query)
    except ProviderError as exc:
        manifest.errors.append(str(exc))
        return []
    admitted = []
    for url in urls[:MAX_SOURCES]:
        try:
            snapshot, spans = admit_url(store, url)
        except (FetchError, BlockedDestination) as exc:
            manifest.errors.append(f"could not retrieve {url}: {exc}")
            continue
        index.index(snapshot, spans)
        admitted.append(snapshot.id)
    return admitted
