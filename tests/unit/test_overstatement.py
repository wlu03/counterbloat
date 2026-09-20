from backend.ingestion.sections import MD_AND_A, RISK_FACTORS, Section
from backend.models import AssertionType, Claim, SourceSpan
from backend.orchestration import overstatement
from backend.verification import xbrl


def _span(i, text):
    return SourceSpan(id=f"s{i}", document_id="d", kind="paragraph", text=text, start=i, end=i + 1)


SECTIONS = {RISK_FACTORS: Section(
    item=RISK_FACTORS, title="Risk Factors",
    spans=[_span(0, "Demand for our product may fall if customers reduce their spending "
                    "sharply during an economic downturn in any of our main markets.")])}


def _claim(text, kind=AssertionType.reported_achievement, **fields):
    return Claim(id="c1", document_id="call", span_id="s", text=text, start=0, end=len(text),
                 assertion_type=kind, **fields)


def _row(claim, monkeypatch, stance=xbrl.NOT_FOUND, filed=None, sections=SECTIONS):
    monkeypatch.setattr(overstatement.xbrl, "verify",
                        lambda c, cik, period=None: xbrl.Check(c.id, stance, tag="Revenues", filed=filed,
                                                  accession="0001-15-1", note="stub"))
    monkeypatch.setattr(overstatement, "hedging_delta", lambda a, b: 0.0)
    return overstatement.row_for(claim, speaker="Person1", segment="prepared", cik="0000012345",
                                 sections=sections, accession="0001-15-1")


def test_a_row_carries_both_measures_and_its_evidence(monkeypatch):
    row = _row(_claim("Demand for our product is strong."), monkeypatch)
    assert row.speaker == "Person1" and row.segment == "prepared"
    assert 0.0 <= row.rhetorical_inflation <= 1.0
    agents = {e["agent"] for e in row.evidence}
    assert agents == {"xbrl-verifier", "risk-matcher"}
    assert all(e.get("accession") for e in row.evidence)


def test_a_claim_nothing_looked_at_abstains(monkeypatch):
    row = _row(_claim("We had a good stretch."), monkeypatch, sections={})
    assert row.verdict == overstatement.ABSTAIN and row.evidence_gap is None
    assert "no filing passage" in row.note or "anything to compare" in row.note


def test_a_contradicted_figure_is_reported_as_contradicted(monkeypatch):
    row = _row(_claim("Revenue was $76.1 million.", kind=AssertionType.numerical_comparison,
                      metric="revenue", value="$76.1 million", unit="USD millions"),
               monkeypatch, stance=xbrl.CONTRADICTS)
    assert row.verdict == overstatement.CONTRADICTED and row.evidence_gap == 1.0


def test_a_confirmed_figure_is_consistent_however_loud_the_wording(monkeypatch):
    row = _row(_claim("Revenue was a world-class $76.1 million.",
                      kind=AssertionType.numerical_comparison, metric="revenue",
                      value="$76.1 million"), monkeypatch, stance=xbrl.SUPPORTS)
    assert row.verdict == overstatement.CONSISTENT and row.evidence_gap == 0.0
    # The wording is still recorded as loud; it does not change the verdict.
    assert row.puffery_per_100w > 0


def test_rows_serialise_for_the_table(monkeypatch):
    rows = [_row(_claim("Demand is strong."), monkeypatch)]
    out = overstatement.as_dicts(rows)
    assert out[0]["claim_id"] == "c1" and isinstance(out[0]["evidence"], list)


def test_a_wording_difference_alone_is_not_a_contradiction(monkeypatch):
    monkeypatch.setattr(overstatement.xbrl, "verify",
                        lambda c, cik, period=None: xbrl.Check(c.id, xbrl.NOT_FOUND, note="stub"))
    monkeypatch.setattr(overstatement, "hedging_delta", lambda a, b: 4.0)
    row = overstatement.row_for(_claim("Demand for our product is strong."), speaker="Person1",
                                segment="prepared", cik="0000012345", sections=SECTIONS,
                                accession="0001-15-1")
    # The gap records the difference, but no agent disagreed, so the verdict does not say so.
    assert row.evidence_gap is not None and row.evidence_gap > 0
    assert row.verdict == overstatement.CONSISTENT


def test_the_word_measures_read_the_whole_turn_not_one_sentence(monkeypatch):
    monkeypatch.setattr(overstatement.xbrl, "verify",
                        lambda c, cik, period=None: xbrl.Check(c.id, xbrl.NOT_FOUND, note="stub"))
    seen = {}

    def record(claim_text, passage):
        seen["text"] = claim_text
        return 0.0

    monkeypatch.setattr(overstatement, "hedging_delta", record)
    overstatement.row_for(_claim("Demand is strong."), speaker="Person1", segment="prepared",
                          cik="0000012345", sections=SECTIONS, accession="a",
                          turn="Demand is strong. We will always deliver on that.")
    assert "We will always deliver" in seen["text"]


def test_a_later_restatement_is_added_as_context_without_changing_the_verdict(monkeypatch):
    from backend.ingestion.labels import Event
    monkeypatch.setattr(overstatement.xbrl, "verify",
                        lambda c, cik, period=None: xbrl.Check(c.id, xbrl.SUPPORTS, tag="Revenues",
                                                               accession="a", note="stub"))
    monkeypatch.setattr(overstatement, "hedging_delta", lambda a, b: 0.0)
    monkeypatch.setattr(overstatement.outcomes, "events",
                        lambda cik, item: [Event(cik=cik, item="4.02", filed_at="2015-09-10",
                                                 accession="r-1")])
    row = overstatement.row_for(_claim("Revenue was $76.1 million."), speaker="Person1",
                                segment="prepared", cik="0000012345", sections=SECTIONS,
                                accession="a", call_date="2015-04-22")
    later = [e for e in row.evidence if e["agent"] == "outcome-checker"]
    assert later and later[0]["stance"] == "context" and later[0]["months_after"] == 5
    # A restatement months later does not turn a confirmed figure into a contradicted one.
    assert row.verdict == overstatement.CONSISTENT
