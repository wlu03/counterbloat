"""Turn HTML, plain text, or PDF bytes into passages with offsets into one normalized text."""
from __future__ import annotations

import io
import re
import unicodedata
import zlib
from types import SimpleNamespace
from typing import Callable

from lxml import html

from backend.models import SourceSpan, TableCell, TableRow

PARSER_VERSION = "parse-v2"
MAX_INFLATED = 200_000_000
MAX_PASSAGE_CHARS = 800
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


_SYMBOL = re.compile(r"(?:US|C|A|HK)?[$€£¥]")  # a currency sign in a cell of its own
_CLOSER = re.compile(r"[)%]+|pts|bps")           # a sign in its own cell that ends the value before it
_VALUE = re.compile(r"\(?-?(?:US|C|A|HK)?[$€£¥]?\s?\d[\d,]*(?:\.\d+)?\s?%?\)?%?")
_YEAR = re.compile(r"(?:19|20)\d{2}")

Cell = tuple[int, int, str, bool]  # first column, last column, text, whether it is a <th>


def _grid(row) -> list[Cell]:
    """The cells of one row placed on the table's column grid. A colspan widens a cell."""
    cells, column = [], 0
    for cell in row.findall("./*"):
        width = _span(cell)
        cells.append((column, column + width - 1, _visible_text(cell), cell.tag == "th"))
        column += width
    return cells


def _label(cells: list[Cell]) -> str:
    return cells[0][2] if cells and cells[0][0] == 0 else ""


def _is_value(text: str) -> bool:
    # A year is a column label far more often than it is a figure.
    return bool(_VALUE.fullmatch(text) or _SYMBOL.fullmatch(text)) and not _YEAR.fullmatch(text)


_NOTE = re.compile(r"\(.+\)")  # a note about every row, such as "(in millions)"


def _header_rows(rows: list[list[Cell]]) -> int:
    """How many leading rows are header rows.

    A row of <th> cells is a header row. So is a row that holds only a bracketed note. So is a row
    with no figure in it, when its first cell is empty (filings put period labels in ordinary
    cells above the figures) or when it is the first row with a label and another row follows it.
    """
    count, labelled = 0, False
    for position, cells in enumerate(rows):
        filled = [c for c in cells if c[2]]
        others = [c for c in filled if c[0] != 0]
        note = not others and bool(_NOTE.fullmatch(_label(cells)))
        th_row = all(c[3] for c in filled)
        plain = bool(others) and not any(_is_value(c[2]) for c in others)
        first_labelled = bool(_label(cells)) and not labelled and position + 1 < len(rows)
        if not (th_row or note or (plain and (not _label(cells) or first_labelled))):
            break
        labelled = labelled or (bool(_label(cells)) and not note)
        count += 1
    return count


def _values(cells: list[Cell]) -> list[tuple[int, str]]:
    """The non-empty cells after the label as (column, text).

    Filings put a currency sign, the number, and a percent sign or closing bracket in cells of
    their own. The signs are joined to their number, and the value keeps the number's column.
    """
    values: list[list] = []
    sign = ""
    for first, _, text, _ in cells:
        if not text or first == 0:
            continue
        if _SYMBOL.fullmatch(text):
            sign = text
        elif _CLOSER.fullmatch(text) and values:
            values[-1][1] += text
        else:
            values.append([first, sign + text])
            sign = ""
    return [(column, text) for column, text in values]


def _table_rows(table) -> list[tuple[str, TableRow]]:
    caption = table.find("./caption")
    caption_text = _visible_text(caption) if caption is not None else None
    # Rows of a nested table belong to that table, which is visited on its own.
    rows = [_grid(r) for r in table.iter("tr") if next(r.iterancestors("table")) is table]
    rows = [cells for cells in rows if any(c[2] for c in cells)]  # drops empty sizing rows
    split = _header_rows(rows)
    headers = rows[:split]

    def heading(column: int) -> str:
        # Header rows are read top to bottom, so "Three Months Ended" comes before its date. A
        # header cell that spans several columns labels each of them.
        found = [c[2] for cells in headers for c in cells if c[0] <= column <= c[1] and c[2]]
        return " ".join(dict.fromkeys(found))

    if caption_text is None:
        # A bracketed note in the label column of the header rows, such as "(in millions)",
        # applies to every row, so it is kept with each of them. A column name is not.
        notes = [_label(cells) for cells in headers if _NOTE.fullmatch(_label(cells))]
        caption_text = " ".join(dict.fromkeys(notes)) or None
    result = []
    for cells in rows[split:]:
        # The number's own column is looked up first, then the column of its currency sign.
        pairs = [TableCell(header=heading(column) or heading(column - 1), text=text)
                 for column, text in _values(cells)]
        record = TableRow(caption=caption_text, row_label=_label(cells), cells=pairs)
        # The row text keeps the label, headers, and units together so they are retrieved as one.
        text = " | ".join(filter(None, [caption_text, _label(cells)]
                                 + [f"{p.header}: {p.text}" if p.header else p.text for p in pairs]))
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


def _passages(text: str) -> list[str]:
    """Split on blank lines, then split a long block at sentence ends."""
    result = []
    for block in re.split(r"\n\s*\n", text):
        current = ""
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z‘“\"(])", normalize(block)):
            if current and len(current) + len(sentence) > MAX_PASSAGE_CHARS:
                result.append(current)
                current = ""
            current = f"{current} {sentence}".strip()
        if current:
            result.append(current)
    return result


def _pdf_blocks(content: bytes, transcribe: Transcriber | None,
                flags: list[str]) -> list[tuple[str, str, TableRow | None, int | None]]:
    import pdfplumber
    from pdfminer import pdftypes

    pdftypes.zlib = _CappedZlib()
    blocks = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            # Text flow follows the order in the file, which keeps the columns of a page apart.
            text = page.extract_text(use_text_flow=True) or ""
            if not text.strip() and transcribe is not None:
                # The page is an image. Text read from it by a model is flagged, because a
                # quote from it has not been checked against a text layer.
                picture = io.BytesIO()
                page.to_image(resolution=150).original.save(picture, format="PNG")
                text = transcribe(picture.getvalue())
                if "ocr_text" not in flags:
                    flags.append("ocr_text")
            blocks += [("paragraph", passage, None, number) for passage in _passages(text)]
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
        blocks = [("paragraph", passage, None, None)
                  for passage in _passages(content.decode("utf-8", "replace"))]
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
