"""Turn a score into a probability, fitted on the claims that can be checked exactly.

A claim naming a filed metric, a number and a period can be settled against the figure the
company filed, so those claims carry an outcome without anyone labelling them. Those outcomes fit
the curve. It is then applied to the claims that cannot be settled that way, which is most of
them: forward-looking statements, company-defined measures, and wording with no figure in it.

That transfer is the method's weak point and is reported with every fitted curve. The checkable
claims are not a sample of the rest; they are the ones precise enough to check. A curve fitted on
them may be wrong about vaguer wording in a direction this cannot measure.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Below this many outcomes, or with only one kind of outcome, a fitted curve would read as
# confident on the strength of a handful of claims. Nothing is returned instead.
MIN_OUTCOMES = 30
MIN_PER_CLASS = 5


class NotEnoughOutcomes(Exception):
    pass


@dataclass(frozen=True)
class Calibration:
    """A fitted curve and what it was fitted on."""
    n: int
    positives: int
    brier: float
    base_rate: float
    bins: list[tuple[float, float, int]] = field(default_factory=list)
    note: str = ""
    _curve: object = None

    def probability(self, score: float) -> float:
        return float(self._curve.predict([score])[0])


def brier(probabilities: list[float], outcomes: list[int]) -> float:
    """Mean squared error of the probabilities against what happened."""
    if not probabilities:
        return 0.0
    return sum((p - o) ** 2 for p, o in zip(probabilities, outcomes)) / len(probabilities)


def reliability(probabilities: list[float], outcomes: list[int], bins: int = 5
                ) -> list[tuple[float, float, int]]:
    """Predicted against observed frequency, one row per band. The rows a reader checks."""
    rows = []
    for i in range(bins):
        low, high = i / bins, (i + 1) / bins
        inside = [(p, o) for p, o in zip(probabilities, outcomes)
                  if (low <= p < high or (i == bins - 1 and p == 1.0))]
        if not inside:
            continue
        rows.append((sum(p for p, _ in inside) / len(inside),
                     sum(o for _, o in inside) / len(inside), len(inside)))
    return rows


def fit(scores: list[float], outcomes: list[int]) -> Calibration:
    """Fit a curve mapping score to probability, or refuse when there is too little to fit on."""
    if len(scores) != len(outcomes):
        raise ValueError("every score needs an outcome")
    positives = sum(outcomes)
    if len(outcomes) < MIN_OUTCOMES:
        raise NotEnoughOutcomes(
            f"{len(outcomes)} checked claims is below the {MIN_OUTCOMES} needed to fit a curve")
    if positives < MIN_PER_CLASS or len(outcomes) - positives < MIN_PER_CLASS:
        raise NotEnoughOutcomes(
            f"{positives} of {len(outcomes)} disagreed; each outcome needs {MIN_PER_CLASS}")
    from sklearn.isotonic import IsotonicRegression

    curve = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
    curve.fit(scores, outcomes)
    fitted = [float(p) for p in curve.predict(scores)]
    return Calibration(
        n=len(outcomes), positives=positives, brier=round(brier(fitted, outcomes), 4),
        base_rate=round(positives / len(outcomes), 4),
        bins=[(round(a, 3), round(b, 3), c) for a, b, c in reliability(fitted, outcomes)],
        note=("fitted on claims a filed figure could settle; applying it to claims that cannot "
              "be settled that way assumes the two behave alike, which is untested"),
        _curve=curve)
