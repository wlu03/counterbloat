"""Preserve source bytes by content hash and record a snapshot.

Admitting the same bytes again keeps the stored url and dates and fills only the missing ones.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from backend.config import env
from backend.db import Store
from backend.ingestion import parse as parser
from backend.ingestion.fetch import FetchError, fetch
from backend.models import DocumentSnapshot, SourceSpan


def object_dir() -> Path:
    path = Path(env("OBJECT_STORE_DIR", "objects"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def admit(store: Store, content: bytes, media_type: str, url: str | None = None,
          published_at: datetime | None = None, admissible_from: datetime | None = None,
          transcribe: parser.Transcriber | None = None) -> tuple[DocumentSnapshot, list[SourceSpan]]:
    digest = hashlib.sha256(content).hexdigest()
    document_id = f"doc-{digest[:16]}"
    existing = store.get("documents", document_id, DocumentSnapshot)
    if existing is not None:
        media_type = existing.media_type  # a second upload must not re-parse stored passages
        url = existing.url or url
        published_at = existing.published_at or published_at
        admissible_from = existing.admissible_from or admissible_from
    (object_dir() / digest).write_bytes(content)
    try:
        text, spans, flags = parser.parse(document_id, content, media_type, transcribe)
    except Exception as exc:
        raise FetchError(f"cannot parse document: {exc}") from exc
    (object_dir() / f"{digest}.txt").write_text(text)
    snapshot = DocumentSnapshot(
        id=document_id, url=url, sha256=digest, media_type=media_type, published_at=published_at,
        retrieved_at=datetime.now(UTC), admissible_from=admissible_from or published_at,
        parser_version=parser.PARSER_VERSION, quality_flags=flags)
    store.put("documents", document_id, snapshot)
    for span in spans:
        store.put("spans", span.id, span, document_id=document_id)
    return snapshot, spans


def admit_url(store: Store, url: str, **options) -> tuple[DocumentSnapshot, list[SourceSpan]]:
    content, media_type, final_url = fetch(url)
    return admit(store, content, media_type, url=final_url, **options)


def normalized_text(snapshot: DocumentSnapshot) -> str:
    return (object_dir() / f"{snapshot.sha256}.txt").read_text()
