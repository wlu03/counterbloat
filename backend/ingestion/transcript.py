"""Read an aligned earnings call: one sentence per line with the acoustic measures for that line.

The MAEC corpus stores each call as text.txt, one sentence per line, and features.csv, one row of
Praat measures per sentence in the same order. Speaker labels are a separate file and cover only
part of the corpus. Speaker names are removed from the text upstream, so a speaker is identified
only by a label that is consistent within one call.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

# The operator says this when prepared remarks end. Only some calls keep the line.
QA_MARKER = re.compile(r"question[- ]and[- ]answer|begin the question", re.I)
PREPARED, QA, UNKNOWN = "prepared", "qa", "unknown"


@dataclass(frozen=True)
class Sentence:
    call_id: str
    index: int
    text: str
    speaker: str | None
    segment: str
    features: dict[str, float]

    @property
    def words(self) -> int:
        return len(self.text.split())

    @property
    def words_per_second(self) -> float | None:
        length = self.features.get("Audio Length")
        return self.words / length if length else None


def call_ids(dataset: Path) -> list[str]:
    return sorted(d.name for d in Path(dataset).iterdir() if (d / "text.txt").is_file())


def _features(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        rows = []
        for row in csv.DictReader(handle):
            values = {}
            for key, value in row.items():
                if key is None:
                    continue
                try:
                    values[key.strip()] = float(value)
                except (TypeError, ValueError):
                    continue  # Praat writes --undefined-- when it cannot measure a line.
            rows.append(values)
    return rows


def _speakers(path: Path, count: int) -> list[str | None]:
    """Speaker labels are aligned by position and are missing for part of the corpus."""
    if not path.is_file():
        return [None] * count
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        labels = [row["Person"].strip() or None for row in csv.DictReader(handle)]
    if len(labels) != count:
        return [None] * count
    return labels


def qa_start(lines: list[str]) -> int | None:
    """Index of the first question-and-answer sentence, or None when the call does not mark it."""
    for i, line in enumerate(lines):
        if QA_MARKER.search(line):
            return i + 1
    return None


def read_call(dataset: Path, call_id: str, labels: Path | None = None) -> list[Sentence]:
    folder = Path(dataset) / call_id
    lines = [l.strip() for l in (folder / "text.txt").read_text(
        encoding="utf-8", errors="replace").splitlines() if l.strip()]
    rows = _features(folder / "features.csv")
    if len(rows) != len(lines):
        raise ValueError(f"{call_id}: {len(lines)} sentences but {len(rows)} feature rows")
    speakers = _speakers(Path(labels) / call_id / "text.csv" if labels else Path("none"),
                         len(lines))
    start = qa_start(lines)
    sentences = []
    for i, (text, row, speaker) in enumerate(zip(lines, rows, speakers)):
        if start is None:
            segment = UNKNOWN
        else:
            segment = QA if i >= start else PREPARED
        sentences.append(Sentence(call_id, i, text, speaker, segment, row))
    return sentences


def within_speaker_delta(sentences: list[Sentence], column: str) -> dict[int, float]:
    """Each sentence's measure minus that speaker's own mean over the prepared remarks.

    The speaker is their own control, which removes differences between people and recordings.
    A call with no marked prepared section, or a speaker who does not appear in it, yields no
    value for those sentences rather than a number measured against someone else.
    """
    baselines: dict[str | None, list[float]] = {}
    for s in sentences:
        value = s.features.get(column)
        if s.segment == PREPARED and value is not None:
            baselines.setdefault(s.speaker, []).append(value)
    means = {speaker: sum(v) / len(v) for speaker, v in baselines.items() if v}
    deltas = {}
    for s in sentences:
        value = s.features.get(column)
        if s.segment == QA and value is not None and s.speaker in means:
            deltas[s.index] = value - means[s.speaker]
    return deltas
