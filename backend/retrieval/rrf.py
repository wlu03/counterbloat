"""Reciprocal rank fusion. The fused score depends only on ranks.

It does not measure whether a passage is true.
"""
from __future__ import annotations


def fuse(rankings: list[list[str]], k: int = 60) -> list[str]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda item: (-scores[item], item))
