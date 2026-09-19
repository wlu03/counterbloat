"""Ablation systems from specification section 18.3."""
from __future__ import annotations

from backend.config import Settings

# A2 to A5 are settings of the pipeline. A0 and A1 are separate baselines in baselines.py.
# A6 and A7 are not implemented.
ABLATIONS = {
    "A2": {"jev_routing": False, "protected_compression": False},
    "A3": {"jev_routing": True, "protected_compression": False},
    "A4": {"jev_routing": False, "protected_compression": True},
    "A5": {"jev_routing": True, "protected_compression": True},
}


def settings_for(name: str, base: Settings) -> Settings:
    settings = base.model_copy(deep=True)
    for key, value in ABLATIONS[name].items():
        setattr(settings.optimization, key, value)
    return settings
