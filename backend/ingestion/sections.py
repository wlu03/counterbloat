"""Split an annual report into its numbered items.

A filing names each item twice: once in the table of contents and once where the section starts.
Both can be laid out as a table, so the kind of span does not separate them. A contents line ends
with the page the item is on and a heading does not, so the page number is what is tested. Items
must also appear in ascending order, which discards a stray mention inside a sentence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from backend.models import SourceSpan

HEADING = re.compile(r"^\s*item\s+(\d{1,2})\s*([A-C])?\s*[.:\-–—]?\s*(.{0,60})", re.I)
# A contents line finishes with the page the item is on, written on its own or
# after the word Page. A heading carries no page number.
CONTENTS_LINE = re.compile(r"\|\s*(?:page:?\s*)?\d{1,4}\s*$", re.I)
# Wording a filer uses when the answer to an item lives in another document.
ELSEWHERE = re.compile(r"incorporated\s+(?:herein\s+)?by\s+reference"
                       r"|appears?\s+in\s+a\s+separate\s+section"
                       r"|set\s+forth\s+in\s+(?:the\s+)?exhibit", re.I)
BUSINESS, RISK_FACTORS, MD_AND_A = "1", "1A", "7"


@dataclass(frozen=True)
class Section:
    item: str
    title: str
    spans: list[SourceSpan]

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.spans)

    @property
    def incorporated_by_reference(self) -> bool:
        """True when the item holds only a pointer to where the content actually is.

        A filer may answer an item by naming another document, usually an exhibit. Nothing in the
        section can then be matched against a claim, and an empty match is not evidence of absence.
        """
        return len(self.text.split()) < 120 and bool(ELSEWHERE.search(self.text))


def _order(item: str) -> tuple[int, str]:
    found = re.fullmatch(r"(\d{1,2})([A-C]?)", item)
    return (int(found.group(1)), found.group(2)) if found else (99, "")


def headings(spans: list[SourceSpan]) -> list[tuple[int, str, str]]:
    """Position, item and title of each heading that starts a section, in ascending item order."""
    found = []
    for i, span in enumerate(spans):
        match = HEADING.match(span.text)
        if not match or CONTENTS_LINE.search(span.text):
            continue
        item = f"{int(match.group(1))}{(match.group(2) or '').upper()}"
        title = match.group(3).strip(" .:-")
        if found and _order(item) <= _order(found[-1][1]):
            continue  # A later mention of an earlier item is a reference, not a heading.
        found.append((i, item, title))
    return found


def sections(spans: list[SourceSpan]) -> dict[str, Section]:
    """Every item found, each holding the spans from its heading to the next one."""
    marks = headings(spans)
    out = {}
    for place, (index, item, title) in enumerate(marks):
        end = marks[place + 1][0] if place + 1 < len(marks) else len(spans)
        out[item] = Section(item=item, title=title, spans=spans[index + 1:end])
    return out
