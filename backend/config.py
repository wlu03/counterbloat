"""Application settings: one YAML file for behaviour, environment variables for secrets."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from backend.models import Mode


class Retrieval(BaseModel):
    candidates_per_query: int = 30
    retained_passages_per_question: int = 8
    preserve_critical_context: bool = True


class Optimization(BaseModel):
    jev_routing: bool = True
    protected_compression: bool = True


class AssessmentSettings(BaseModel):
    # Any other value fails when the file is loaded.
    updater: Literal["linguistic", "full_context", "evidence_accumulator"] = "linguistic"
    # Prior and tempering of the experimental accumulator. 0.5 is a neutral scenario prior. It
    # was not estimated from data.
    prior: float = 0.5
    tempering: float = 1.0
    public_numeric_probability: Literal[False] = False
    review_original_decisive_evidence: Literal[True] = True


class Settings(BaseModel):
    mode: Mode = Mode.live
    max_investigation_rounds: int = 2
    max_follow_up_rounds: int = 1  # extra rounds a reviewer's request for a check may use
    retrieval: Retrieval = Retrieval()
    optimization: Optimization = Optimization()
    assessment: AssessmentSettings = AssessmentSettings()

    def config_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


def load_settings(path: str | Path = "config/app.yaml") -> Settings:
    data = yaml.safe_load(Path(path).read_text()) if Path(path).exists() else {}
    return Settings.model_validate(data or {})


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value or None
