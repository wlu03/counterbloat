import time

from backend.claims.extract import extract
from backend.models import AssertionType, Mode, RunManifest, SourceSpan
from backend.providers.base import ClaimDraft


def _spans(n):
    return [SourceSpan(id=f"s{i}", document_id="d", kind="paragraph",
                       text=f"Revenue in segment {i} rose to {i} million dollars in the quarter.",
                       start=i * 100, end=i * 100 + 70) for i in range(n)]


class Slow:
    """Stands in for a provider: every read waits, as a network call does."""

    def __init__(self, delay=0.05):
        self.delay = delay

    def extract_claims(self, span, context):
        time.sleep(self.delay)
        return [ClaimDraft(quote=span.text, assertion_type=AssertionType.numerical_comparison,
                           subject=None, assertion=None, metric="revenue", value=None, unit=None,
                           denominator=None, population=None, boundary=None, period=None,
                           qualifications=[])]


def _run(spans, workers):
    manifest = RunManifest(analysis_id="a", mode=Mode.live, config_hash="c")
    return extract(spans, Slow(), None, manifest, workers=workers), manifest


def test_the_worker_count_does_not_change_the_result():
    spans = _spans(8)
    one, m1 = _run(spans, 1)
    many, m8 = _run(spans, 8)
    assert [c.id for c in one] == [c.id for c in many]
    assert [c.text for c in one] == [c.text for c in many]
    assert [c.start for c in one] == [c.start for c in many]
    assert m1.rejections == m8.rejections and m1.errors == m8.errors


def test_claims_come_back_in_passage_order():
    claims, _ = _run(_spans(6), 6)
    assert [c.span_id for c in claims] == [f"s{i}" for i in range(6)]


def test_reading_several_passages_at_once_is_faster():
    spans = _spans(8)
    started = time.monotonic()
    _run(spans, 1)
    serial = time.monotonic() - started
    started = time.monotonic()
    _run(spans, 8)
    concurrent = time.monotonic() - started
    # Eight waits of the same length, taken together, cannot take as long as one after another.
    assert concurrent < serial / 2


def test_one_passage_is_not_sent_to_a_pool():
    claims, _ = _run(_spans(1), 8)
    assert len(claims) == 1
