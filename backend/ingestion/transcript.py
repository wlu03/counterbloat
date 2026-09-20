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
from typing import Callable

from backend.models import SourceSpan

# Transcripts mark the end of prepared remarks in two ways: a heading the transcriber inserted,
# or the moment someone hands the call to the operator. Both are matched, and the earliest wins.
# The patterns are written to be wrong rarely rather than to fire often: on the calls that carry
# the heading, the handoff patterns agree with it to within three sentences about seven times in
# ten and almost never fire earlier. A call whose wording is not matched is left unknown.
QA_MARKER = re.compile(
    r"question[- ]and[- ]answer"
    r"|begin the question"
    r"|open(?:ing)?\s+(?:up\s+)?the\s+lines?\s+(?:up\s+)?(?:for|to)\s+questions?"
    r"|ready\s+(?:for|to\s+take)\s+(?:your\s+)?questions?"
    r"|operator[,.]?\s+(?:do\s+we\s+have|are\s+there|any)\b[^.]{0,25}questions?"
    r"|(?:first|next)\s+question\s+(?:comes|is|will\s+come)\s+from"
    r"|question\s+comes\s+from\s+"
    r"|turn\s+(?:it|the\s+call)\s+(?:back\s+)?(?:over\s+)?to\s+[^.]{0,30}questions?",
    re.I)
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


# A host often previews the agenda in the opening minute, saying the call will later open for
# questions. That announcement matches the same wording as the handoff itself, so the last match
# is taken rather than the first. A boundary that would still leave prepared remarks this short
# is not believed at all, because an opening of a few sentences is the preview, not the handoff.
MIN_PREPARED_SHARE = 0.25


def qa_start(lines: list[str]) -> int | None:
    """Index of the first question-and-answer sentence, or None when the call does not mark it."""
    hits = [i for i, line in enumerate(lines) if QA_MARKER.search(line)]
    if not hits:
        return None
    start = hits[-1] + 1
    if lines and start < MIN_PREPARED_SHARE * len(lines):
        return None
    return start


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


def within_speaker(sentences: list[Sentence], value: Callable[[Sentence], float | None]
                   ) -> dict[int, float]:
    """Each sentence's value minus that speaker's own mean over the prepared remarks.

    The speaker is their own control, which removes differences between people and recordings.
    A call with no marked prepared section, or a speaker who does not appear in it, yields no
    value for those sentences rather than a number measured against someone else.
    """
    baselines: dict[str | None, list[float]] = {}
    for s in sentences:
        got = value(s)
        if s.segment == PREPARED and got is not None:
            baselines.setdefault(s.speaker, []).append(got)
    means = {speaker: sum(v) / len(v) for speaker, v in baselines.items() if v}
    deltas = {}
    for s in sentences:
        got = value(s)
        if s.segment == QA and got is not None and s.speaker in means:
            deltas[s.index] = got - means[s.speaker]
    return deltas


def speech_rate_delta(sentences: list[Sentence]) -> dict[int, float]:
    """Change in words a second, from a speaker's prepared remarks to their answers.

    Filled pauses are edited out of these transcripts, so disfluency cannot be counted from them.
    Speaking rate survives editing, because it is the recorded length of a sentence against the
    words that were said in it.
    """
    return within_speaker(sentences, lambda s: s.words_per_second)


def within_speaker_delta(sentences: list[Sentence], column: str) -> dict[int, float]:
    """Each sentence's measure minus that speaker's own mean over the prepared remarks.

    The speaker is their own control, which removes differences between people and recordings.
    A call with no marked prepared section, or a speaker who does not appear in it, yields no
    value for those sentences rather than a number measured against someone else.
    """
    return within_speaker(sentences, lambda s: s.features.get(column))


def speakers_in_prepared(sentences: list[Sentence]) -> set[str]:
    """Labels that speak during prepared remarks.

    Analysts do not speak before the operator opens the line, so on a call whose boundary was
    found these labels are the company's own speakers. On a call with no boundary the set is
    empty, because nothing distinguishes the two sides.
    """
    return {s.speaker for s in sentences if s.segment == PREPARED and s.speaker}


def spans(sentences: list[Sentence], document_id: str | None = None
          ) -> tuple[str, list[SourceSpan]]:
    """Lay the call out as one text with one span per sentence, as the filing parser does.

    Claim extraction reads spans, so a call has to be presented the same way a filing is. Each
    span keeps the offsets of its sentence in the joined text, so a claim quote resolves back to
    a position in the call.
    """
    document = document_id or (sentences[0].call_id if sentences else "")
    parts, made, offset = [], [], 0
    for s in sentences:
        parts.append(s.text)
        made.append(SourceSpan(id=f"{document}:{s.index}", document_id=document, kind="paragraph",
                               text=s.text, start=offset, end=offset + len(s.text)))
        offset += len(s.text) + 1
    for i, span in enumerate(made):
        if i:
            made[i] = span.model_copy(update={"prev_id": made[i - 1].id})
    for i, span in enumerate(made[:-1]):
        made[i] = span.model_copy(update={"next_id": made[i + 1].id})
    return "\n".join(parts), made


@dataclass(frozen=True)
class Turn:
    """Consecutive sentences from one speaker without another speaker in between."""
    call_id: str
    speaker: str | None
    segment: str
    first: int
    last: int
    text: str

    def holds(self, index: int) -> bool:
        return self.first <= index <= self.last


def turns(sentences: list[Sentence]) -> list[Turn]:
    """Group the call into speaking turns.

    A word-category density taken over one sentence is mostly zero, because the strong and weak
    modal lists hold a few dozen words between them. A turn is the smallest unit that gives such
    a measure enough words to mean anything.
    """
    out: list[Turn] = []
    for s in sentences:
        if out and out[-1].speaker == s.speaker and out[-1].segment == s.segment \
                and out[-1].last == s.index - 1:
            last = out[-1]
            out[-1] = Turn(last.call_id, last.speaker, last.segment, last.first, s.index,
                           f"{last.text} {s.text}")
        else:
            out.append(Turn(s.call_id, s.speaker, s.segment, s.index, s.index, s.text))
    return out


def turn_holding(turns_: list[Turn], index: int) -> Turn | None:
    for turn in turns_:
        if turn.holds(index):
            return turn
    return None
