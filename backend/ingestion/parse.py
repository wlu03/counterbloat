"""Turn HTML, plain text, or PDF bytes into passages with offsets into one normalized text."""
from __future__ import annotations

import io
import re
from itertools import accumulate
import unicodedata
import zlib
from types import SimpleNamespace
from typing import Callable

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
    # NFKC turns a superscript digit into a plain digit, which would make 10⁶ read as 106.
    text = re.sub(r"([⁰¹²³⁴-⁹]+)", r"^\1", text)
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


def _span(cell) -> int:
    value = (cell.get("colspan") or "").strip()
    return int(value) if re.fullmatch(r"[1-9]\d?", value) else 1  # 1 to 99; anything else is 1


def _table_rows(table) -> list[tuple[str, TableRow]]:
    caption = table.find("./caption")
    caption_text = _visible_text(caption) if caption is not None else None
    # Rows of a nested table belong to that table, which is visited on its own.
    rows = [r for r in table.iter("tr") if next(r.iterancestors("table")) is table]
    if not rows:
        return []
    # A header cell that spans several columns labels each of them.
    headers = [text for cell in rows[0].findall("./*")
               for text in [_visible_text(cell)] * _span(cell)]
    result = []
    for row in rows[1:]:
        found = row.findall("./*")
        cells = [_visible_text(cell) for cell in found]
        if not cells or not any(cells):
            continue
        columns = accumulate(_span(cell) for cell in found)  # the column where the next cell starts
        pairs = [TableCell(header=headers[i] if i < len(headers) else "", text=cell)
                 for i, cell in zip(columns, cells[1:])]
        record = TableRow(caption=caption_text, row_label=cells[0], cells=pairs)
        # The row text keeps the label, headers, and units together so they are retrieved as one.
        text = " | ".join(filter(None, [caption_text, cells[0]]
                                 + [f"{p.header}: {p.text}" for p in pairs]))
        result.append((text, record))
    return result


def _leaf_div(element) -> bool:
    # A <div> that holds no block, table, or other <div> is a paragraph.
    return element.tag == "div" and not any(
        d.tag in _BLOCKS or d.tag in ("div", "table") for d in element.iterdescendants())


def _html_blocks(content: bytes) -> list[tuple[str, str, TableRow | None, int | None]]:
    try:
        # Without this, bytes that declare no charset are read as Latin-1.
        root = html.document_fromstring(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        root = html.document_fromstring(content)
    _strip_hidden(root)
    for sup in root.iter("sup"):
        sup.text = "^" + (sup.text or "")  # keeps 10<sup>6</sup> from reading as 106
    for element in list(root.iter("div", "table", *_BLOCKS)):
        # Text that follows a block inside a container becomes its own paragraph.
        if (element.tail or "").strip() and not any(
                a.tag == "table" or a.tag in _BLOCKS for a in element.iterancestors()):
            wrapper = html.Element("p")
            wrapper.text, element.tail = element.tail, None
            element.addnext(wrapper)
    for element in root.iter("br", "p", "div", "li", "tr", "td", "th", *_BLOCKS):
        element.tail = " " + (element.tail or "")  # a line break or block end separates words
    blocks = []
    for element in root.iter():
        if element.tag == "table":
            blocks += [("table_row", text, record, None) for text, record in _table_rows(element)]
        elif (element.tag in _BLOCKS or _leaf_div(element)) and not any(
                a.tag == "table" or a.tag in _BLOCKS for a in element.iterancestors()):
            text = _visible_text(element)
            if not text:
                continue
            marker = " ".join([element.get("class") or "", element.get("id") or ""]).lower()
            kind = "footnote" if "footnote" in marker else _BLOCKS.get(element.tag, "paragraph")
            blocks.append((kind, text, None, None))
    body = root.find("body")
    if not blocks and body is not None:  # text held in tags that are not listed above
        blocks = [("paragraph", normalize(p), None, None)
                  for p in re.split(r"\n\s*\n", body.text_content()) if normalize(p)]
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


Transcriber = Callable[[bytes], str]  # PNG bytes of one page to its text


def _pdf_blocks(content: bytes, transcribe: Transcriber | None,
                flags: list[str]) -> list[tuple[str, str, TableRow | None, int | None]]:
    import pdfplumber
    from pdfminer import pdftypes

    pdftypes.zlib = _CappedZlib()
    blocks = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if not text.strip() and transcribe is not None:
                # The page is an image. Text read from it by a model is flagged, because a
                # quote from it has not been checked against a text layer.
                picture = io.BytesIO()
                page.to_image(resolution=150).original.save(picture, format="PNG")
                text = transcribe(picture.getvalue())
                if "ocr_text" not in flags:
                    flags.append("ocr_text")
            for paragraph in re.split(r"\n\s*\n", text):
                if normalize(paragraph):
                    blocks.append(("paragraph", normalize(paragraph), None, number))
    return blocks


def parse(document_id: str, content: bytes, media_type: str,
          transcribe: Transcriber | None = None) -> tuple[str, list[SourceSpan], list[str]]:
    """Return (normalized text, spans, quality flags)."""
    flags: list[str] = []
    if media_type == "application/pdf":
        blocks = _pdf_blocks(content, transcribe, flags)
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
