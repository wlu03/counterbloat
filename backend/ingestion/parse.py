"""Turn HTML, plain text, or PDF bytes into passages with offsets into one normalized text."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, replace
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


def _span(cell, name: str = "colspan") -> int:
    value = (cell.get(name) or "").strip()
    return int(value) if re.fullmatch(r"[1-9]\d?", value) else 1  # 1 to 99; anything else is 1


_SYMBOL = re.compile(r"(?:US|C|A|HK)?[$€£¥]")  # a currency sign in a cell of its own
_CLOSER = re.compile(r"[)%]+|pts|bps")           # a sign in its own cell that ends the value before it
_DASH = re.compile(r"[-–—]|to")                  # joins the two ends of a range
_VALUE = re.compile(r"\(?-?(?:US|C|A|HK)?[$€£¥]?\s?\d[\d,]*(?:\.\d+)?\s?%?\)?%?")
_YEAR = re.compile(r"(?:19|20)\d{2}")
_NOTE = re.compile(r"\(.+\)")  # a note about every row, such as "(in millions)"


@dataclass(frozen=True)
class Cell:
    first: int   # first and last column on the table's grid
    last: int
    text: str
    th: bool
    carried: bool = False  # placed here by a rowspan in a row above


def _grids(rows) -> list[list[Cell]]:
    """Every row's cells placed on the table's column grid.

    A colspan widens a cell. A rowspan keeps a cell in the rows below it, where the cells of those
    rows are placed in the columns that are left.
    """
    grids, carry = [], []  # carry holds (cell, rows still to cover)
    for row in rows:
        taken = [cell for cell, _ in carry]
        placed, later, column = list(taken), [], 0
        for element in row.findall("./*"):
            while any(c.first <= column <= c.last for c in taken):
                column = next(c.last for c in taken if c.first <= column <= c.last) + 1
            cell = Cell(column, column + _span(element) - 1, _visible_text(element),
                        element.tag == "th")
            placed.append(cell)
            if _span(element, "rowspan") > 1:
                later.append((replace(cell, carried=True), _span(element, "rowspan") - 1))
            column = cell.last + 1
        carry = [(cell, left - 1) for cell, left in carry if left > 1] + later
        grids.append(sorted(placed, key=lambda c: c.first))
    return grids


def _label(cells: list[Cell]) -> str:
    return cells[0].text if cells and cells[0].first == 0 else ""


def _is_value(text: str) -> bool:
    # A year is a column label far more often than it is a figure. A sign on its own is not a
    # figure either: filings use "$" and "%" as the sub-headers of a "Change" column.
    return bool(_VALUE.fullmatch(text)) and not _YEAR.fullmatch(text)


def _header_rows(rows: list[list[Cell]]) -> int:
    """How many leading rows are header rows.

    A row of <th> cells is a header row. So is a row that holds only a bracketed note. So is a row
    with no figure in it when its first cell is empty or a note, because filings put period
    labels in ordinary cells above the figures. A row with a label and no figure is a header row
    when it is the first row that names columns and another row follows, or when every other cell
    in it is a short period label, as in "June 30, | 2026 | 2025".
    """
    count, columns_named, named_seen, titles = 0, False, False, 0
    for position, cells in enumerate(rows):
        own = [c for c in cells if c.text and not c.carried]
        others = [c for c in own if c.first != 0]
        label = next((c.text for c in own if c.first == 0), "")
        named = bool(label) and not _NOTE.fullmatch(label)
        plain = bool(others) and not any(_is_value(c.text) for c in others)
        periods = all(len(c.text) <= 40 and _YEAR.search(c.text) for c in others)
        # Column names are short. A first row of long text belongs to a table with no header row.
        first_names = not columns_named and position + 1 < len(rows) and all(len(c.text) <= 120 for c in others)
        # Below a row of group headers, one row may name the columns, as in "Exhibit Number |
        # Exhibit Description | Form". Such names are short and hold no digits, which a row of
        # text data below the header rows does not.
        second_names = columns_named and not named_seen and all(
            len(c.text) <= 40 and not re.search(r"\d", c.text) for c in others)
        if not others and named and not columns_named:
            titles += 1  # a title above the header rows, if header rows do follow
        elif not ((bool(own) and all(c.th for c in own)) or (not others and bool(label) and not named)
                  or (plain and (not named or periods or first_names or second_names))):
            break
        columns_named = columns_named or bool(others)
        named_seen = named_seen or (named and bool(others))
        count += 1
    # Rows with only a label and no header row after them are section headings, which are data.
    return count if columns_named or count > titles else 0


def _row_label(cells: list[Cell]) -> Cell | None:
    """The cell that names a data row: the one in the first column, or, when that is empty, the
    first text cell, because some filings indent a label with an empty leading cell."""
    filled = [c for c in cells if c.text]
    if filled and (filled[0].first == 0 or (len(filled) > 1 and not _is_value(filled[0].text)
                                            and not _SYMBOL.fullmatch(filled[0].text)
                                            and not _DASH.fullmatch(filled[0].text))):
        return filled[0]
    return None


def _values(cells: list[Cell], label: Cell | None) -> list[tuple[int, int, str]]:
    """The non-empty cells other than the label as (first column, last column, text).

    Filings put a currency sign, the number, and a percent sign or closing bracket in cells of
    their own. The signs are joined to their number, and the value keeps the number's columns. A
    dash in its own cell directly between two numbers joins them into one range.
    """
    filled = [c for c in cells if c.text and c is not label]
    # Each value: the number's first and last column, its text, and the last column of any sign
    # after it. The header is looked up over the number's columns only, because a closing sign
    # often sits in a padding column under the next header.
    values: list[list] = []
    sign, joining = "", False
    for position, cell in enumerate(filled):
        following = filled[position + 1] if position + 1 < len(filled) else None
        if _SYMBOL.fullmatch(cell.text):
            sign = cell.text
        elif _CLOSER.fullmatch(cell.text) and values:
            values[-1][2] += cell.text
            values[-1][3] = cell.last
        elif (_DASH.fullmatch(cell.text) and values and following is not None
              and values[-1][3] == cell.first - 1 and following.first == cell.last + 1
              and (_is_value(following.text) or _YEAR.fullmatch(following.text))):
            # A dash with nothing beside it is a nil figure, so only a dash between two
            # adjoining numbers is a range.
            values[-1][2] += f" {cell.text} "
            joining = True
        elif joining:
            values[-1][2] += sign + cell.text
            values[-1][3], sign, joining = cell.last, "", False
        else:
            values.append([cell.first, cell.last, sign + cell.text, cell.last])
            sign = ""
    return [(first, last, text) for first, last, text, _ in values]


def _table_rows(table) -> list[tuple[str, TableRow]]:
    caption = table.find("./caption")
    caption_text = _visible_text(caption) if caption is not None else None
    # Rows of a nested table belong to that table, which is visited on its own.
    rows = _grids([r for r in table.iter("tr") if next(r.iterancestors("table")) is table])
    rows = [cells for cells in rows if any(c.text and not c.carried for c in cells)]  # drops sizing rows
    split = _header_rows(rows)
    headers = rows[:split]

    def column_labels(cells: list[Cell]) -> list[Cell]:
        # "Year Ended June 30," beside the years 2026 and 2025 is the first half of each date. The
        # trailing comma is what shows the label is an unfinished date and not a column name.
        label = _label(cells)
        others = [c for c in cells if c.first != 0 and c.text and not _NOTE.fullmatch(c.text)]
        if label.endswith(",") and others and all(_YEAR.fullmatch(c.text) for c in others):
            return [replace(c, text=f"{label} {c.text}") for c in others]
        return others

    labels = [column_labels(cells) for cells in headers]

    def heading(first: int, last: int) -> str:
        # Header rows are read top to bottom, so "Three Months Ended" comes before its date. A
        # header cell labels every column it spans, and a wide value takes every header above it.
        found = [c.text for row in labels for c in row if c.first <= last and first <= c.last]
        return " ".join(dict.fromkeys(found))

    if caption_text is None:
        # Text in the header rows that applies to every row is kept with each of them: a bracketed
        # note such as "(in millions)" wherever it sits, a title in a row of its own, or a period
        # in the label column such as "Three Months Ended June 30, 2026". A column name is not.
        kept = [c.text for cells in headers for c in cells
                if c.text and not c.carried and (_NOTE.fullmatch(c.text) or (c.first == 0 and (
                    _YEAR.search(c.text) or not any(o.text for o in cells if o.first != 0))))]
        caption_text = " ".join(dict.fromkeys(kept)) or None
    result = []
    for cells in rows[split:]:
        label = _row_label(cells)
        # The number's own columns are looked up first, then the column of its currency sign.
        pairs = [TableCell(header=heading(first, last) or heading(first - 1, first - 1), text=text)
                 for first, last, text in _values(cells, label)]
        name = label.text if label else ""
        record = TableRow(caption=caption_text, row_label=name, cells=pairs)
        # The row text keeps the label, headers, and units together so they are retrieved as one.
        text = " | ".join(filter(None, [caption_text, name]
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
