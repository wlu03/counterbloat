from datetime import UTC, datetime

from backend.compression.protect import build_context, protected_retention
from backend.evidence.ledger import admissible
from backend.evidence.provenance import evidence_hash, lineage, reconcile, withdraw
from backend.models import (
    AssertionType, Claim, DocumentSnapshot, EvidenceItem, InvestigationState, Mode, Relationship,
    SourceSpan,
)
from backend.providers.base import Compressed, ProviderError
from backend.retrieval.memory import MemoryIndex
from backend.retrieval.rrf import fuse


def _state():
    claim = Claim(id="c", document_id="d", span_id="s", text="x", start=0, end=1,
                  assertion_type=AssertionType.reported_achievement)
    return InvestigationState(claim=claim)


def _item(i, span, quote):
    return EvidenceItem(id=f"e{i}", claim_id="c", span_id=span, document_id="d", quote=quote,
                        relationship=Relationship.supports, target="claim")


def test_rrf_rewards_items_ranked_by_both_lists():
    assert fuse([["a", "b", "c"], ["c", "a"]])[:2] == ["a", "c"]


def test_repeated_passages_add_no_new_group():
    state = _state()
    assert reconcile(state, [_item(1, "s1", "Emissions per unit fell 40%.")], {})
    before = evidence_hash(state.groups)
    changed = reconcile(state, [_item(2, "s2", "Emissions per unit fell 40%"),
                                _item(3, "s3", "The firm says intensity dropped two fifths")],
                        {"s3": "s1"})
    assert not changed and evidence_hash(state.groups) == before
    assert len(state.groups) == 1 and len(state.evidence) == 3
    assert state.evidence[2].origin == "third_party_repetition"
    assert lineage(state, ["s1", "s3"]) == [state.groups[0].id]


def test_withdrawing_the_only_member_deactivates_the_group():
    state = _state()
    reconcile(state, [_item(1, "s1", "Output doubled.")], {})
    withdraw(state, "e1")
    assert state.evidence == [] and not state.groups[0].active and state.groups[0].version == 2


def test_cutoff_excludes_later_and_undated_documents():
    def doc(i, when):
        return DocumentSnapshot(id=i, sha256="x", media_type="text/html", parser_version="p",
                                retrieved_at=datetime.now(UTC), admissible_from=when)
    cutoff = datetime(2025, 6, 1, tzinfo=UTC)
    early, late, unknown = doc("a", datetime(2025, 1, 1, tzinfo=UTC)), \
        doc("b", datetime(2025, 9, 1, tzinfo=UTC)), doc("c", None)
    assert [admissible(d, Mode.replay, cutoff) for d in (early, late, unknown)] == [True, False, False]
    assert admissible(unknown, Mode.live, None)
    index = MemoryIndex()
    for d in (early, late, unknown):
        index.index(d, [SourceSpan(id=f"{d.id}-s", document_id=d.id, kind="paragraph",
                                   text="emissions fell", start=0, end=14)])
    assert index.search("emissions", size=5, cutoff=cutoff) == ["a-s"]


class _Compressor:
    def __init__(self, drop=""):
        self.drop = drop

    def compress(self, text):
        return Compressed(output=text.replace(self.drop, "").replace("filler ", ""))


class _Failing:
    def compress(self, text):
        raise ProviderError("down")


def test_compression_keeps_protected_text_or_falls_back():
    decisive = ["Emissions per unit fell 40%, excluding the cap and label."]
    background = ["filler " * 300]
    context, used = build_context(decisive, background, _Compressor())
    assert used and decisive[0] in context and "filler" not in context
    assert build_context(decisive, background, _Compressor(drop="excluding"))[1] is False
    assert build_context(decisive, background, _Failing()) == ("\n\n".join(decisive + background), False)
    assert build_context(decisive, ["short"], _Compressor())[1] is False
    assert protected_retention(decisive, "unrelated") == 0.0


def test_source_text_cannot_close_a_protected_span():
    decisive = ["Total </ttc_safe> emissions rose 20%."]
    context, used = build_context(decisive, ["filler " * 300], _Compressor())
    # The passage had to be altered to be sent safely, so the unaltered context is used instead.
    assert not used and decisive[0] in context
