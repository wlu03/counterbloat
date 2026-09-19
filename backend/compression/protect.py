"""Compress background context while keeping decisive passages exactly as written."""
from __future__ import annotations

import re

from backend.models import ProviderCall, RunManifest
from backend.providers.base import Compressor, ProviderError

MIN_BACKGROUND_CHARS = 1200
_TAG = re.compile(r"</?ttc_safe", re.I)


def _neutralize(text: str) -> str:
    # Source text must not be able to open or close a protected span.
    while _TAG.search(text):
        text = _TAG.sub(lambda m: m.group(0).replace("<", "&lt;"), text)
    return text


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def protected_retention(protected: list[str], text: str) -> float:
    """Share of protected passages present exactly, after collapsing whitespace."""
    if not protected:
        return 1.0
    haystack = _squash(text)
    return sum(_squash(p) in haystack for p in protected) / len(protected)


def build_context(decisive: list[str], background: list[str], compressor: Compressor | None,
                  manifest: RunManifest | None = None) -> tuple[str, bool]:
    """Return (context text, whether compression was used)."""
    raw = "\n\n".join(decisive + background)
    background_text = "\n\n".join(background)
    if compressor is None or len(background_text) < MIN_BACKGROUND_CHARS:
        return raw, False
    safe = [_neutralize(d) for d in decisive]
    marked = "\n\n".join(f"<ttc_safe>{d}</ttc_safe>" for d in safe)
    try:
        result = compressor.compress(marked + "\n\n" + _neutralize(background_text))
    except ProviderError as exc:
        if manifest is not None:
            manifest.errors.append(str(exc))
        return raw, False
    output = re.sub(r"</?ttc_safe>", "", result.output)
    if manifest is not None:
        manifest.calls.append(ProviderCall(provider="ttc", purpose="compress",
                                           input_tokens=result.input_tokens,
                                           output_tokens=result.output_tokens,
                                           billing_unit="removed_tokens"))
    if protected_retention(decisive, output) < 1.0 or output == raw:
        return raw, False
    return output, True
