"""Turn HTML, plain text, or PDF bytes into passages with offsets into one normalized text."""
from __future__ import annotations

import io
import re
import unicodedata

from lxml import html

from backend.models import SourceSpan, TableCell, TableRow

PARSER_VERSION = "parse-v1"
_DROP = ("script", "style", "noscript", "template", "iframe")
_HIDDEN = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0", re.I)
_BLOCKS = {"p": "paragraph", "li": "paragraph", "blockquote": "paragraph",
           "figcaption": "caption", "h1": "heading", "h2": "heading", "h3": "heading",
           "h4": "heading", "h5": "heading", "h6": "heading"}


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace(" ", " ")
    # Unicode tag characters and zero-width characters can carry text a reader never sees.
    text = re.sub(r"[\U000E0000-\U000E007F​-‏⁠﻿]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _visible_text(element) -> str:
    return normalize(element.text_content())


def _strip_hidden(root) -> None:
    for element in list(root.iter()):
        if not isinstance(element.tag, str):  # comments and processing instructions
            element.getparent().remove(element) if element.getparent() is not None else None
            continue
        hidden = (element.tag in _DROP or element.get("hidden") is not None
                  or element.get("aria-hidden") == "true"
                  or _HIDDEN.search(element.get("style") or ""))
        if hidden and element.getparent() is not None:
            element.drop_tree()


def _table_rows(table) -> list[tuple[str, TableRow]]:
    caption = table.find(".//caption")
    caption_text = _visible_text(caption) if caption is not None else None
    rows = table.findall(".//tr")
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
        elif element.tag in _BLOCKS and element.xpath("ancestor::table") == []:
            text = _visible_text(element)
            if not text:
                continue
            marker = " ".join([element.get("class") or "", element.get("id") or ""]).lower()
            kind = "footnote" if "footnote" in marker or "note" in marker else _BLOCKS[element.tag]
            blocks.append((kind, text, None, None))
    return blocks


def _pdf_blocks(content: bytes) -> list[tuple[str, str, TableRow | None, int | None]]:
    import pdfplumber

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
