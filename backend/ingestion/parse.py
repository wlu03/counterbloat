"""Turn HTML, plain text, or PDF bytes into passages with offsets into one normalized text."""
from __future__ import annotations

import io
import re
import unicodedata
import zlib
from types import SimpleNamespace

from lxml import html

from backend.models import SourceSpan, TableCell, TableRow

PARSER_VERSION = "parse-v1"
MAX_INFLATED = 200_000_000
_DROP = ("script", "style", "noscript", "template", "iframe")
# The font-size pattern matches 0, 0px, and 0.0em, and does not match 0.9em.
_HIDDEN = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![\d.]*[1-9])",
                     re.I)
_BLOCKS = {"p": "paragraph", "li": "paragraph", "blockquote": "paragraph",
           "figcaption": "caption", "h1": "heading", "h2": "heading", "h3": "heading",
           "h4": "heading", "h5": "heading", "h6": "heading"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    # Unicode tag characters and zero-width characters can carry text a reader never sees.
    text = re.sub(r"[\U000E0000-\U000E007F​-‏⁠﻿]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _visible_text(element) -> str:
    return normalize(element.text_content())


def _strip_hidden(root) -> None:
    for element in list(root.iter()):
        if not isinstance(element.tag, str):  # comments and processing instructions
            if element.getparent() is not None:
                element.drop_tree()  # drop_tree keeps the visible text that follows the node
            continue
        hidden = (element.tag in _DROP or element.get("hidden") is not None
                  or element.get("aria-hidden") == "true"
                  or _HIDDEN.search(element.get("style") or ""))
        if hidden and element.getparent() is not None:
            element.drop_tree()


def _table_rows(table) -> list[tuple[str, TableRow]]:
    caption = table.find("./caption")
    caption_text = _visible_text(caption) if caption is not None else None
    # Rows of a nested table belong to that table, which is visited on its own.
    rows = [r for r in table.iter("tr") if next(r.iterancestors("table")) is table]
    if not rows:
        return []
    headers = [_visible_text(cell) for cell in rows[0].findall("./*")]
    result = []
    for row in rows[1:]:
        cells = [_visible_text(cell) for cell in row.findall("./*")]
        if not cells or not any(cells):
            continue
        pairs = [TableCell(header=headers[i] if i < len(headers) else "", text=cell)
                 for i, cell in enumerate(cells[1:], start=1)]
        record = TableRow(caption=caption_text, row_label=cells[0], cells=pairs)
        # The row text keeps the label, headers, and units together so they are retrieved as one.
        text = " | ".join(filter(None, [caption_text, cells[0]]
                                 + [f"{p.header}: {p.text}" for p in pairs]))
        result.append((text, record))
    return result


def _html_blocks(content: bytes) -> list[tuple[str, str, TableRow | None, int | None]]:
    root = html.fromstring(content)
    _strip_hidden(root)
    blocks = []
    for element in root.iter():
        if element.tag == "table":
            blocks += [("table_row", text, record, None) for text, record in _table_rows(element)]
        elif element.tag in _BLOCKS and not any(
                a.tag == "table" or a.tag in _BLOCKS for a in element.iterancestors()):
            text = _visible_text(element)
            if not text:
                continue
            marker = " ".join([element.get("class") or "", element.get("id") or ""]).lower()
            kind = "footnote" if "footnote" in marker or "note" in marker else _BLOCKS[element.tag]
            blocks.append((kind, text, None, None))
    return blocks


class _CappedZlib:
    """Replaces zlib inside pdfminer, which inflates every stream in memory with no limit."""
    error = zlib.error

    def __init__(self) -> None:
        self.left = MAX_INFLATED

    def decompress(self, data: bytes, inflater=None) -> bytes:
        out = (inflater or zlib.decompressobj()).decompress(data, self.left + 1)
        self.left -= len(out)
        if self.left < 0:
            raise ValueError("PDF inflates past the size limit")
        return out

    def decompressobj(self) -> SimpleNamespace:
        # pdfminer retries a corrupt stream through this call, so the retry uses the same limit.
        inflater = zlib.decompressobj()
        return SimpleNamespace(decompress=lambda data: self.decompress(data, inflater))


def _pdf_blocks(content: bytes) -> list[tuple[str, str, TableRow | None, int | None]]:
    import pdfplumber
    from pdfminer import pdftypes

    pdftypes.zlib = _CappedZlib()
    blocks = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            for paragraph in re.split(r"\n\s*\n", page.extract_text() or ""):
                if normalize(paragraph):
                    blocks.append(("paragraph", normalize(paragraph), None, number))
    return blocks


def parse(document_id: str, content: bytes, media_type: str) -> tuple[str, list[SourceSpan], list[str]]:
    """Return (normalized text, spans, quality flags)."""
    flags: list[str] = []
    if media_type == "application/pdf":
        blocks = _pdf_blocks(content)
        if not blocks:
            flags.append("no_text_layer")
    elif media_type == "text/plain":
        paragraphs = re.split(r"\n\s*\n", content.decode("utf-8", "replace"))
        blocks = [("paragraph", normalize(p), None, None) for p in paragraphs if normalize(p)]
    else:
        blocks = _html_blocks(content)

    spans: list[SourceSpan] = []
    parts: list[str] = []
    offset = 0
    for index, (kind, text, table, page) in enumerate(blocks):
        spans.append(SourceSpan(id=f"{document_id}-s{index}", document_id=document_id, kind=kind,
                                text=text, start=offset, end=offset + len(text), page=page,
                                table=table))
        parts.append(text)
        offset += len(text) + 2  # passages are joined with a blank line
    notes = [s.id for s in spans if s.kind == "footnote"]
    for index, span in enumerate(spans):
        span.prev_id = spans[index - 1].id if index else None
        span.next_id = spans[index + 1].id if index + 1 < len(spans) else None
        if span.kind != "footnote":
            span.note_ids = notes
    return "\n\n".join(parts), spans, flags
