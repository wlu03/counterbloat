import pytest

from backend.claims import lexicon

HEADER = "Word,Negative,Positive,Uncertainty,Litigious,Strong_Modal,Weak_Modal,Constraining\n"
ROWS = ("LOSS,2009,0,0,0,0,0,0\n"
        "STRONG,0,2009,0,0,0,0,0\n"
        "WILL,0,0,0,0,2009,0,0\n"
        "ALWAYS,0,0,0,0,2009,0,0\n"
        "MAY,0,0,2009,0,0,2009,0\n"
        "COULD,0,0,0,0,0,2009,0\n"
        "REQUIRE,0,0,0,0,0,0,2009\n")


@pytest.fixture
def dictionary(tmp_path):
    path = tmp_path / "lm.csv"
    path.write_text(HEADER + ROWS)
    lexicon.load.cache_clear()
    return path


def test_a_word_counts_for_every_category_that_marks_it(dictionary):
    loaded = lexicon.load(dictionary)
    assert "may" in loaded["Uncertainty"] and "may" in loaded["Weak_Modal"]
    assert loaded["Strong_Modal"] == frozenset({"will", "always"})


def test_densities_are_per_hundred_words(dictionary):
    # Four words, one of which is strong modal.
    found = lexicon.densities("We will grow fast", dictionary)
    assert found["Strong_Modal"] == 25.0
    assert found["Weak_Modal"] == 0.0


def test_an_empty_text_scores_zero_rather_than_failing(dictionary):
    assert lexicon.densities("", dictionary)["Negative"] == 0.0


def test_a_firm_claim_against_a_hedged_passage_gives_a_positive_delta(dictionary):
    delta = lexicon.hedging_delta("We will always deliver", "Results may vary and could fall",
                                  dictionary)
    # The claim is half strong modal; the passage is one third weak modal.
    assert delta == pytest.approx(50.0 - (2 / 6) * 100, abs=0.01)


def test_a_vague_claim_against_a_hedged_passage_gives_a_negative_delta(dictionary):
    # The delta is strong modal in the claim minus weak modal in the passage, so it falls below
    # zero when the claim asserts nothing firmly and the filing still hedges.
    assert lexicon.hedging_delta("Results vary", "Results may fall", dictionary) < 0


def test_the_delta_compares_two_different_categories(dictionary):
    # Strong modal in the claim against weak modal in the passage, so the same firm wording on
    # both sides still scores above zero. It is not a like-for-like difference.
    assert lexicon.hedging_delta("We will deliver", "We will deliver",
                                 dictionary) == pytest.approx(100 / 3, abs=0.01)
    assert lexicon.hedging_delta("Results vary", "Results vary", dictionary) == 0.0


def test_a_missing_dictionary_says_how_to_get_it(tmp_path):
    lexicon.load.cache_clear()
    with pytest.raises(lexicon.LexiconMissing, match="datasets.fetch loughran_mcdonald"):
        lexicon.load(tmp_path / "absent.csv")
