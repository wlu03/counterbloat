from backend.ingestion.sections import BUSINESS, MD_AND_A, RISK_FACTORS, headings, sections
from backend.models import SourceSpan


def _spans(rows):
    return [SourceSpan(id=str(i), document_id="d", kind=kind, text=text, start=i, end=i + 1)
            for i, (kind, text) in enumerate(rows)]


CONTENTS = [("table_row", "Item 1. | Business | Page: 3"),
            ("table_row", "Item 1A. | Risk Factors | Page: 13"),
            ("table_row", "Item 7. | Management's Discussion | Page: 20")]
BODY = [("paragraph", "Item 1. Business"),
        ("paragraph", "We operate in one segment."),
        ("paragraph", "Item 1A. Risk Factors"),
        ("paragraph", "Demand may fall."),
        ("paragraph", "Our costs may rise."),
        ("paragraph", "Item 7. Management's Discussion"),
        ("paragraph", "Revenue rose.")]


def test_the_table_of_contents_is_not_mistaken_for_the_sections():
    found = sections(_spans(CONTENTS + BODY))
    assert set(found) == {BUSINESS, RISK_FACTORS, MD_AND_A}
    assert found[RISK_FACTORS].text == "Demand may fall.\nOur costs may rise."
    assert found[BUSINESS].text == "We operate in one segment."


def test_a_heading_laid_out_as_a_table_still_starts_a_section():
    # Some filers put the real heading in a one-cell table, with no page number.
    rows = CONTENTS + [("table_row", "Item 1A. | Risk Factors"), ("paragraph", "Demand may fall.")]
    assert sections(_spans(rows))[RISK_FACTORS].text == "Demand may fall."


def test_items_must_climb_so_a_later_mention_is_not_a_heading():
    rows = BODY + [("paragraph", "Item 1A. Risk Factors is discussed above.")]
    marks = headings(_spans(rows))
    assert [item for _, item, _ in marks] == [BUSINESS, RISK_FACTORS, MD_AND_A]


def test_an_item_answered_by_pointing_elsewhere_is_marked():
    rows = [("paragraph", "Item 7. Management's Discussion"),
            ("paragraph", "Management's Discussion appears in a separate section of this report."),
            ("paragraph", "Item 8. Financial Statements")]
    found = sections(_spans(rows))
    assert found[MD_AND_A].incorporated_by_reference is True


def test_a_real_section_is_not_marked_as_pointing_elsewhere():
    assert sections(_spans(BODY))[RISK_FACTORS].incorporated_by_reference is False
