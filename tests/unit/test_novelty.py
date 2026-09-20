from backend.models import SourceSpan
from backend.retrieval import novelty


def _spans(texts, prefix="s"):
    return [SourceSpan(id=f"{prefix}{i}", document_id="d", kind="paragraph", text=t,
                       start=i, end=i + 1) for i, t in enumerate(texts)]


BOILERPLATE = ("Our results depend on general economic conditions and consumer spending levels "
               "in the markets where we operate.")
REWORDED = ("Our results depend on general economic conditions and on consumer spending levels "
            "across the markets in which we operate.")
NEW_RISK = ("A regulator opened an inquiry into how we recognise revenue from multi-year "
            "subscription arrangements sold through resellers.")


def test_a_passage_carried_over_word_for_word_is_not_added():
    [found] = novelty.compare(_spans([BOILERPLATE]), _spans([BOILERPLATE], "p"))
    assert found.status == novelty.CARRIED_OVER and found.closest == 1.0


def test_a_passage_only_reworded_is_still_carried_over():
    [found] = novelty.compare(_spans([REWORDED]), _spans([BOILERPLATE], "p"))
    assert found.status == novelty.CARRIED_OVER and found.closest >= novelty.SAME


def test_a_genuinely_new_risk_is_reported_as_added():
    [found] = novelty.compare(_spans([NEW_RISK]), _spans([BOILERPLATE], "p"))
    assert found.status == novelty.ADDED and found.closest < novelty.SAME
    # The two share no vocabulary, so there is no earlier passage to point at.
    assert found.closest == 0.0 and found.closest_span_id is None


def test_the_nearest_earlier_passage_is_named_when_there_is_one():
    partly = "Consumer spending levels in our markets may fall during a downturn."
    [found] = novelty.compare(_spans([partly]), _spans([NEW_RISK, BOILERPLATE], "p"))
    assert found.closest_span_id == "p1" and 0.0 < found.closest


def test_added_returns_only_the_new_passages():
    current = _spans([BOILERPLATE, NEW_RISK])
    found = novelty.added(current, _spans([BOILERPLATE], "p"))
    assert [n.span_id for n in found] == ["s1"]


def test_everything_is_added_when_there_is_no_earlier_filing():
    found = novelty.compare(_spans([BOILERPLATE, NEW_RISK]), [])
    assert all(n.status == novelty.ADDED and n.closest == 0.0 for n in found)


def test_similarity_ignores_length_differences():
    # The short passage is wholly contained in the long one, so it is the same point.
    assert novelty.similarity("regulator opened inquiry revenue recognition",
                              NEW_RISK) >= novelty.SAME
