"""The answers are half of a call. A run that reads only the prepared remarks measures the
scripted half, so this checks a run-sized selection against the corpus itself."""
import json
import pathlib

import pytest

from backend.ingestion.transcript import QA, PREPARED, read_call, spans, speakers_in_prepared
from backend.orchestration.overstatement import company_spans

CORPUS = pathlib.Path("datasets/maec/source")
TRACES = pathlib.Path("results/complete_traces.json")
RUN_LIMIT = 12  # what backend.api.calls.run_workflow sends by default


def _corpus():
    dataset = next((p for p in CORPUS.rglob("MAEC_Dataset") if p.is_dir()), None)
    labels = next((p for p in CORPUS.rglob("MAEC_Dataset_Person_Label") if p.is_dir()), None)
    if dataset is None or labels is None or not TRACES.is_file():
        pytest.skip("the aligned call corpus is not fetched here")
    return dataset, labels, json.loads(TRACES.read_text())


def test_a_run_sized_selection_reads_the_answers_too():
    dataset, labels, traces = _corpus()
    checked = 0
    for trace in traces[:5]:
        sentences = read_call(dataset, trace["call"], labels)
        if not any(s.segment == QA for s in sentences):
            continue
        _, made = spans(sentences)
        segments = {s.index: s.segment for s in sentences}
        chosen = company_spans(made, sentences, speakers_in_prepared(sentences),
                               min_chars=100, limit=RUN_LIMIT)
        read = {segments[int(s.id.split(":")[1])] for s in chosen}
        assert QA in read, f"{trace['call']} sent no answers to the pipeline"
        assert PREPARED in read, f"{trace['call']} sent no prepared remarks"
        checked += 1
    assert checked, "no call in the sample had a detectable question-and-answer boundary"


def test_the_answers_are_not_a_small_corner_of_a_call():
    dataset, labels, traces = _corpus()
    sentences = read_call(dataset, traces[0]["call"], labels)
    if not any(s.segment == QA for s in sentences):
        pytest.skip("this call marks no boundary")
    answers = sum(1 for s in sentences if s.segment == QA)
    assert answers >= sum(1 for s in sentences if s.segment == PREPARED) / 2
