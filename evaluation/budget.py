"""Stop a paid run after a fixed number of provider calls."""
from __future__ import annotations

from backend.providers.base import ProviderError


class Budgeted:
    """Wrap a provider. Every call counts, and calls past the limit raise ProviderError."""

    def __init__(self, llm, max_calls: int) -> None:
        self._llm, self.max_calls, self.calls = llm, max_calls, 0
        self.refused = False  # whether any call was turned away

    def __getattr__(self, name: str):
        method = getattr(self._llm, name)

        def counted(*args, **kwargs):
            if self.calls >= self.max_calls:
                self.refused = True
                raise ProviderError(f"call budget of {self.max_calls} is used up")
            self.calls += 1
            return method(*args, **kwargs)
        return counted
