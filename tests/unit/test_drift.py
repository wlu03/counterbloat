import pytest

from backend.models import SourceSpan
from backend.retrieval import drift

DICT = "Word,Negative,Positive,Uncertainty,Litigious,Strong_Modal,Weak_Modal,Constraining\n" \
       "WILL,0,0,0,0,2009,0,0\nALWAYS,0,0,0,0,2009,0,0\n" \
       "MAY,0,0,2009,0,0,2009,0\nMIGHT,0,0,0,0,0,2009,0\n"

FIRM = "We will always meet our published emission reduction targets at every site we operate."
SOFT = "We may meet our published emission reduction targets at sites we operate, and might not."
OTHER = "Foreign exchange rates fluctuate between reporting periods in the markets we serve."


@pytest.fixture
def path(tmp_path):
    from backend.claims import lexicon
    p = tmp_path / "lm.csv"
    p.write_text(DICT)
    lexicon.load.cache_clear()
    return p


def _span(i, text):
    return SourceSpan(id=f"s{i}", document_id="d", kind="paragraph", text=text, start=0, end=1)


def test_the_same_commitment_put_less_firmly_is_weakened(path):
    found = drift.follow(_span(1, SOFT), [_span(0, FIRM)], path=path)
    assert found.status == drift.WEAKENED and found.strength_change < 0
    assert found.prior_span_id == "s0" and found.similarity >= drift.SAME


def test_the_same_commitment_put_more_firmly_is_firmer(path):
    found = drift.follow(_span(0, FIRM), [_span(1, SOFT)], path=path)
    assert found.status == drift.FIRMER and found.strength_change > 0


def test_the_same_wording_is_unchanged(path):
    found = drift.follow(_span(1, FIRM), [_span(0, FIRM)], path=path)
    assert found.status == drift.UNCHANGED and found.strength_change == 0.0


def test_a_passage_with_no_counterpart_is_not_found(path):
    found = drift.follow(_span(1, OTHER), [_span(0, FIRM)], path=path)
    assert found.status == drift.NOT_FOUND and found.prior_quote is None


def test_a_commitment_the_later_filing_does_not_make_is_dropped():
    [found] = drift.dropped([_span(1, OTHER)], [_span(0, FIRM)])
    assert found.status == drift.DROPPED and found.quote == FIRM


def test_a_commitment_still_made_is_not_dropped():
    assert drift.dropped([_span(1, FIRM)], [_span(0, FIRM)]) == []


def test_without_the_dictionary_only_the_pairing_is_reported(tmp_path):
    from backend.claims import lexicon
    lexicon.load.cache_clear()
    found = drift.follow(_span(1, SOFT), [_span(0, FIRM)], path=tmp_path / "absent.csv")
    assert found.status == drift.UNCHANGED and found.strength_change is None
    assert found.prior_span_id == "s0" and "dictionary is missing" in found.note
