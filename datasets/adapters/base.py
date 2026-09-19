"""Shared reading and export for dataset adapters.

Each adapter splits a native record into what the model may see and what only the scorer may see.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel


class Example(BaseModel):
    id: str
    dataset: str
    model_visible: dict
    evaluation_only: dict


def read_rows(path: str | Path) -> Iterator[dict]:
    path = Path(path)
    if path.suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as handle:
            yield from csv.DictReader(handle)
    elif path.suffix == ".jsonl":
        with path.open(encoding="utf-8") as handle:
            yield from (json.loads(line) for line in handle if line.strip())
    else:
        yield from json.loads(path.read_text(encoding="utf-8"))


def export(examples: list[Example], visible_path: str | Path, gold_path: str | Path) -> None:
    """Write model inputs and gold labels to separate files. Only the owner can read the gold file."""
    Path(visible_path).parent.mkdir(parents=True, exist_ok=True)
    Path(gold_path).parent.mkdir(parents=True, exist_ok=True)
    with open(visible_path, "w", encoding="utf-8") as visible:
        for e in examples:
            visible.write(json.dumps({"id": e.id, **e.model_visible}) + "\n")
    with open(gold_path, "w", encoding="utf-8") as gold:
        for e in examples:
            gold.write(json.dumps({"id": e.id, **e.evaluation_only}) + "\n")
    os.chmod(gold_path, 0o600)
