"""Experimental numeric update (specification section 21). Not used for public output."""
from dataclasses import dataclass
from math import exp, fsum, isfinite, log, log1p


def finite_number(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a number, not a boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not isfinite(result):
        raise ValueError(f"{name} must be finite")
    return result


def logit(probability: float) -> float:
    p = finite_number(probability, "probability")
    if not 0.0 < p < 1.0:
        raise ValueError("probability must be strictly between 0 and 1")
    return log(p) - log1p(-p)


def sigmoid(value: float) -> float:
    z = finite_number(value, "logit")
    # This branch avoids exponential overflow for large negative logits.
    if z >= 0.0:
        return 1.0 / (1.0 + exp(-z))
    ez = exp(z)
    return ez / (1.0 + ez)


def conditioned_bayes_update(prior: float, bayes_factor: float) -> float:
    """Arithmetic only: the caller must justify the conditional factor."""
    factor = finite_number(bayes_factor, "bayes_factor")
    if factor <= 0.0:
        raise ValueError("bayes_factor must be strictly positive")
    return sigmoid(logit(prior) + log(factor))


@dataclass(frozen=True)
class EvidenceContribution:
    group_id: str
    version: int
    log_evidence: float
    weight: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not self.group_id.strip():
            raise ValueError("group_id must be a nonempty string")
        if type(self.version) is not int or self.version < 1:
            raise ValueError("version must be a positive integer")
        score = finite_number(self.log_evidence, "log_evidence")
        weight = finite_number(self.weight, "weight")
        if not 0.0 <= weight <= 1.0:
            raise ValueError("weight must lie in [0, 1]")
        object.__setattr__(self, "log_evidence", score)
        object.__setattr__(self, "weight", weight)


class EvidenceAccumulator:
    """One active contribution per provenance group; not a truth oracle."""

    def __init__(self, prior: float, tempering: float = 1.0) -> None:
        self._prior_logit = logit(prior)
        self._tempering = finite_number(tempering, "tempering")
        if not 0.0 <= self._tempering <= 1.0:
            raise ValueError("tempering must lie in [0, 1]")
        self._groups: dict[str, EvidenceContribution] = {}

    def upsert(self, contribution: EvidenceContribution) -> bool:
        """Return whether the active ledger changed; reject stale conflicts."""
        old = self._groups.get(contribution.group_id)
        if old is not None:
            if contribution.version < old.version:
                raise ValueError("cannot replace evidence with a stale version")
            if contribution.version == old.version:
                if contribution != old:
                    raise ValueError("same evidence version has conflicting data")
                return False
        self._groups[contribution.group_id] = contribution
        return True

    def withdraw(self, group_id: str) -> bool:
        """Remove an active group; its historical record lives upstream."""
        return self._groups.pop(group_id, None) is not None

    def raw_logit(self) -> float:
        total = fsum(item.weight * item.log_evidence for _, item in sorted(self._groups.items()))
        return finite_number(self._prior_logit + self._tempering * total, "accumulated logit")

    def raw_probability(self) -> float:
        """Uncalibrated experimental score, not a public allegation score."""
        return sigmoid(self.raw_logit())
