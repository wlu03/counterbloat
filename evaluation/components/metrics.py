"""Metrics from specification sections 18 and 19. Inputs are plain lists."""
from __future__ import annotations

from math import log

from backend.models import RunManifest


def precision_recall(predicted: list[bool], gold: list[bool]) -> tuple[float | None, float | None]:
    true_positive = sum(p and g for p, g in zip(predicted, gold))
    precision = true_positive / sum(predicted) if any(predicted) else None
    recall = true_positive / sum(gold) if any(gold) else None
    return precision, recall


def brier(probabilities: list[float], labels: list[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(probabilities, labels)) / len(labels)


def nll(probabilities: list[float], labels: list[int]) -> float:
    # A sum of large log-evidence values rounds to exactly 0 or 1, where the logarithm is undefined.
    clipped = [min(max(p, 1e-12), 1 - 1e-12) for p in probabilities]
    return -sum(y * log(p) + (1 - y) * log(1 - p) for p, y in zip(clipped, labels)) / len(labels)


def acceptance_rate(accepted: list[bool]) -> float:
    return sum(accepted) / len(accepted)


def selective_error(accepted: list[bool], predicted: list, gold: list) -> float | None:
    """Error rate over accepted cases. None when nothing was accepted, because it is undefined."""
    kept = [(p, g) for a, p, g in zip(accepted, predicted, gold) if a]
    return sum(p != g for p, g in kept) / len(kept) if kept else None


def token_reduction(compressed_tokens: int, uncompressed_tokens: int) -> float:
    return 1 - compressed_tokens / uncompressed_tokens


def cost_savings(compressed_cost: float, uncompressed_cost: float) -> float:
    return 1 - compressed_cost / uncompressed_cost


def run_cost(manifest: RunManifest, rates: dict[str, tuple[float, float, float]]) -> float:
    """Token cost of a run. `rates` maps a model to (input, cached input, output) price per token.

    Calls billed in other units, such as removed tokens, are excluded and must be added separately.
    """
    total = 0.0
    for call in manifest.calls:
        if call.billing_unit != "tokens" or call.model not in rates:
            continue
        r_in, r_cached, r_out = rates[call.model]
        total += ((call.input_tokens - call.cached_tokens) * r_in + call.cached_tokens * r_cached
                  + call.output_tokens * r_out)
    return total
