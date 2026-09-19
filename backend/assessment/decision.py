"""Expected-loss choice between flagging, not flagging, and review (section 11.2).

Use only with a probability calibrated for the target. The application does not have one yet.
"""
from __future__ import annotations


def choose_action(p: float, cost_false_positive: float, cost_false_negative: float,
                  cost_review: float) -> str:
    losses = {"flag": cost_false_positive * (1 - p), "no_finding": cost_false_negative * p,
              "review": cost_review}
    return min(losses, key=losses.get)
