import pytest

from backend.ingestion.transcript import (
    PREPARED, QA, UNKNOWN, call_ids, qa_start, read_call, spans,
    speakers_in_prepared, within_speaker_delta,
)

TEXT = ["Revenue grew strongly.", "We will now begin the question-and-answer session.",
        "Can you size the opportunity?", "It is very large."]
FEATURES = ("Mean pitch,Audio Length\n"
            "120.0,2.0\n"
            "110.0,3.0\n"
            "130.0,1.5\n"
            "180.0,2.5\n")
LABELS = "Person,Sentence\nPerson1,a\nPerson2,b\nPerson3,c\nPerson1,d\n"


def _call(tmp_path, text=TEXT, features=FEATURES, labels=LABELS):
    folder = tmp_path / "data" / "20240101_TEST"
    folder.mkdir(parents=True)
    (folder / "text.txt").write_text("\n".join(text))
    (folder / "features.csv").write_text(features)
    if labels is not None:
        marks = tmp_path / "labels" / "20240101_TEST"
        marks.mkdir(parents=True)
        (marks / "text.csv").write_text(labels)
    return tmp_path / "data", tmp_path / "labels"


def test_a_call_is_read_with_its_features_and_speakers(tmp_path):
    data, labels = _call(tmp_path)
    assert call_ids(data) == ["20240101_TEST"]
    sentences = read_call(data, "20240101_TEST", labels)
    assert [s.speaker for s in sentences] == ["Person1", "Person2", "Person3", "Person1"]
    assert [s.segment for s in sentences] == [PREPARED, PREPARED, QA, QA]
    assert sentences[0].features["Mean pitch"] == 120.0
    assert sentences[0].words == 3 and sentences[0].words_per_second == 1.5


def test_a_call_that_never_marks_the_split_is_not_guessed(tmp_path):
    data, labels = _call(tmp_path, text=["One.", "Two.", "Three.", "Four."])
    sentences = read_call(data, "20240101_TEST", labels)
    assert {s.segment for s in sentences} == {UNKNOWN}
    assert qa_start(["One.", "Two."]) is None
    # With no prepared section there is no baseline, so no delta is reported.
    assert within_speaker_delta(sentences, "Mean pitch") == {}


def test_a_measure_praat_could_not_take_is_dropped(tmp_path):
    data, labels = _call(tmp_path, features=("Mean pitch,Audio Length\n"
                                             "--undefined--,2.0\n110.0,3.0\n"
                                             "130.0,1.5\n180.0,2.5\n"))
    sentences = read_call(data, "20240101_TEST", labels)
    assert "Mean pitch" not in sentences[0].features
    assert sentences[1].features["Mean pitch"] == 110.0


def test_the_delta_is_against_the_same_speaker_only(tmp_path):
    data, labels = _call(tmp_path)
    deltas = within_speaker_delta(read_call(data, "20240101_TEST", labels), "Mean pitch")
    # Person1 spoke at 120 in prepared remarks and 180 in Q&A. Person3 has no baseline.
    assert deltas == {3: 60.0}


def test_misaligned_features_are_refused(tmp_path):
    data, labels = _call(tmp_path, features="Mean pitch,Audio Length\n120.0,2.0\n")
    with pytest.raises(ValueError, match="feature rows"):
        read_call(data, "20240101_TEST", labels)


def test_speaker_labels_that_do_not_line_up_are_ignored(tmp_path):
    data, labels = _call(tmp_path, labels="Person,Sentence\nPerson1,a\n")
    assert [s.speaker for s in read_call(data, "20240101_TEST", labels)] == [None] * 4


@pytest.mark.parametrize("line", [
    "We will now begin the question-and-answer session.",
    "Nicole, we are ready to open up the lines for questions.",
    "Karen, we are now ready to open the line for questions.",
    "Operator, do we have any questions.",
    "The first question comes from an analyst at a bank.",
])
def test_the_handoff_to_the_operator_ends_prepared_remarks(line):
    assert qa_start(["Revenue grew.", line, "Can you size it?"]) == 2


@pytest.mark.parametrize("line", [
    "That is a really good question and I will start.",
    "Let me start with your second question regarding margins.",
    "We received a question about pricing during the roadshow.",
])
def test_an_executive_saying_question_does_not_end_prepared_remarks(line):
    assert qa_start(["Revenue grew.", line, "Margins improved."]) is None


def test_sentences_become_spans_whose_offsets_resolve(tmp_path):
    data, labels = _call(tmp_path)
    sentences = read_call(data, "20240101_TEST", labels)
    text, made = spans(sentences)
    assert len(made) == len(sentences)
    for span, sentence in zip(made, sentences):
        assert text[span.start:span.end] == sentence.text
    # Claim extraction only reads these kinds, and the chain lets it look at neighbours.
    assert {s.kind for s in made} == {"paragraph"}
    assert made[0].prev_id is None and made[0].next_id == made[1].id
    assert made[-1].next_id is None


def test_only_the_company_speaks_before_the_line_opens(tmp_path):
    data, labels = _call(tmp_path)
    sentences = read_call(data, "20240101_TEST", labels)
    # Person3 asks the first question, so it is not one of the company's speakers.
    assert speakers_in_prepared(sentences) == {"Person1", "Person2"}


def test_a_call_with_no_boundary_names_no_company_speaker(tmp_path):
    data, labels = _call(tmp_path, text=["One.", "Two.", "Three.", "Four."])
    assert speakers_in_prepared(read_call(data, "20240101_TEST", labels)) == set()


def test_an_agenda_preview_does_not_end_prepared_remarks():
    lines = ["Good afternoon.",
             "And then we will open up the call for the question-and-answer session.",
             *[f"Revenue in segment {i} grew." for i in range(20)],
             "Operator, we are now ready to open the lines for questions.",
             "What drove the margin?"]
    # The preview is at index 1; the real handoff is near the end.
    assert qa_start(lines) == 23


def test_a_boundary_that_leaves_almost_no_prepared_remarks_is_not_believed():
    lines = ["Good afternoon.",
             "And then we will open up the call for the question-and-answer session.",
             *[f"Sentence {i}." for i in range(30)]]
    assert qa_start(lines) is None
