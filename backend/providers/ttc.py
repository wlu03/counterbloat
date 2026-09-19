"""The Token Company adapter: compresses one text through POST /v1/compress."""
from __future__ import annotations

import httpx

from backend.config import env
from backend.providers.base import Compressed, ProviderError

URL = "https://api.thetokencompany.com/v1/compress"


class TokenCompanyCompressor:
    def __init__(self, aggressiveness: float = 0.1) -> None:
        self.key = env("TTC_API_KEY")
        if not self.key:
            raise ProviderError("TTC_API_KEY is not set")
        self.aggressiveness = aggressiveness

    def compress(self, text: str) -> Compressed:
        body = {"model": "bear-2", "input": text,
                "compression_settings": {"aggressiveness": self.aggressiveness}}
        try:
            response = httpx.post(URL, json=body, timeout=30,
                                  headers={"Authorization": f"Bearer {self.key}"})
            response.raise_for_status()
            data = response.json()
            return Compressed(output=data["output"],
                              input_tokens=data.get("original_input_tokens", 0),
                              output_tokens=data.get("output_tokens", 0))
        except Exception as exc:
            raise ProviderError(f"ttc compress failed: {exc}") from exc
