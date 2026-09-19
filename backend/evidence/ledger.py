"""Decide which documents may be used as evidence in a given mode and at a given cutoff."""
from __future__ import annotations

from datetime import datetime

from backend.models import DocumentSnapshot, Mode


def admissible(document: DocumentSnapshot, mode: Mode, cutoff: datetime | None) -> bool:
    if mode == Mode.live or cutoff is None:
        return True
    # A document with unknown availability is not admissible at an earlier date.
    return document.admissible_from is not None and document.admissible_from <= cutoff
