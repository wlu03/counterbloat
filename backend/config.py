"""Application settings: one YAML file for behaviour, environment variables for secrets."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from backend.models import Mode


class Retrieval(BaseModel):
    candidates_per_query: int = 30
    retained_passages_per_question: int = 8
    preserve_critical_context: bool = True
    # When the whole admissible corpus is no larger than this many passages, every passage is
    # shown and nothing is selected. Choosing 8 passages out of 30 that would all have fitted
    # discards evidence for no reason.
    show_whole_corpus_under: int = 40


class Optimization(BaseModel):
    jev_routing: bool = True
    protected_compression: bool = True


class AssessmentSettings(BaseModel):
    # Any other value fails when the file is loaded.
    updater: Literal["linguistic", "full_context", "evidence_accumulator"] = "linguistic"
    # Prior and tempering of the experimental accumulator. 0.5 is a neutral scenario prior. It
    # was not estimated from data.
    prior: float = Field(0.5, gt=0, lt=1)
    tempering: float = Field(1.0, gt=0, le=1)
    public_numeric_probability: Literal[False] = False
    review_original_decisive_evidence: Literal[True] = True


class ReplicationSettings(BaseModel):
    # Limits of the one paid Devin session per repository that an analysis may ask for. No
    # analysis asks for one by default.
    max_acu: int = 10
    timeout_s: int = 3600
    max_claims: int = 5
    max_repositories: int = 1


class Settings(BaseModel):
    mode: Mode = Mode.live
    max_investigation_rounds: int = 2
    max_follow_up_rounds: int = 1  # extra rounds a reviewer's request for a check may use
    retrieval: Retrieval = Retrieval()
    optimization: Optimization = Optimization()
    assessment: AssessmentSettings = AssessmentSettings()
    replication: ReplicationSettings = ReplicationSettings()

    def config_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


def load_settings(path: str | Path = "config/app.yaml") -> Settings:
    data = yaml.safe_load(Path(path).read_text()) if Path(path).exists() else {}
    return Settings.model_validate(data or {})


def env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value or None
