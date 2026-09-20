from backend.ingestion.sections import MD_AND_A, RISK_FACTORS, Section
from backend.models import AssertionType, Claim, SourceSpan
from backend.retrieval import risk_matcher


def _span(i, text):
    return SourceSpan(id=f"s{i}", document_id="d", kind="paragraph", text=text, start=i, end=i + 1)


def _sections(**items):
    return {item: Section(item=item, title=item, spans=[_span(i, t) for i, t in enumerate(texts)])
            for item, texts in items.items()}


CLAIM = Claim(id="c1", document_id="call", span_id="x", text="Demand for our product is strong.",
              start=0, end=1, assertion_type=AssertionType.reported_achievement,
              metric="demand", subject="product")

SECTIONS = _sections(**{
    RISK_FACTORS: ["Demand for our product may fall if customers cut spending in a downturn.",
                   "We depend on a small number of suppliers for key components worldwide."],
    MD_AND_A: ["Revenue rose on higher demand for our product during the period under review."],
})


def test_the_closest_passage_by_word_overlap_comes_first():
    found = risk_matcher.match(CLAIM, SECTIONS, accession="0001-15-1", k=3)
    assert found and found[0].method == risk_matcher.KEYWORD
    assert "may fall" in found[0].quote
    assert found[0].item == RISK_FACTORS and found[0].accession == "0001-15-1"
    assert all(a.score >= b.score for a, b in zip(found, found[1:]))


def test_embeddings_are_used_when_a_model_is_given():
    # The first vector is the claim; the passage nearest it must win regardless of wording.
    def embed(texts):
        return [[1.0, 0.0], [0.0, 1.0], [0.9, 0.1], [0.0, 1.0]]

    found = risk_matcher.match(CLAIM, SECTIONS, embed=embed, k=1)
    assert found[0].method == risk_matcher.EMBEDDING
    assert "suppliers" in found[0].quote


def test_an_embedder_that_returns_nothing_falls_back_to_words():
    found = risk_matcher.match(CLAIM, SECTIONS, embed=lambda texts: [], k=1)
    assert found[0].method == risk_matcher.KEYWORD


def test_an_item_that_points_elsewhere_is_not_searched():
    sections = _sections(**{MD_AND_A: ["Management's discussion appears in a separate section "
                                       "of this annual report and is incorporated by reference."]})
    assert sections[MD_AND_A].incorporated_by_reference is True
    assert risk_matcher.match(CLAIM, sections) == []


def test_a_claim_with_nothing_in_common_matches_nothing():
    sections = _sections(**{RISK_FACTORS: ["Foreign exchange rates fluctuate between periods."]})
    assert risk_matcher.match(CLAIM, sections) == []


def test_short_passages_are_not_candidates():
    sections = _sections(**{RISK_FACTORS: ["Demand may fall."]})
    assert risk_matcher.match(CLAIM, sections) == []


def test_the_search_can_be_limited_to_chosen_passages():
    everything = risk_matcher.match(CLAIM, SECTIONS, k=5)
    assert len(everything) > 1
    # Restricted to one passage, only that passage can be returned.
    only = {everything[-1].span_id}
    limited = risk_matcher.match(CLAIM, SECTIONS, k=5, only=only)
    assert [m.span_id for m in limited] == list(only)


def test_limiting_to_nothing_returns_nothing():
    assert risk_matcher.match(CLAIM, SECTIONS, only=set()) == []
