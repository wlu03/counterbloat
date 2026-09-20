import json

from backend.api import calls


def test_a_call_is_listed_with_the_period_it_reports(tmp_path):
    path = tmp_path / "traces.json"
    path.write_text(json.dumps([
        {"call": "20150422_EXPO", "ticker": "EXPO", "cik": "0000851520", "date": "2015-04-22",
         "tenk": "0001144204-15-012949", "tenk_url": "https://example.invalid/a.htm"},
        {"call": "20160210_NSIT", "ticker": "NSIT", "cik": "0001makes", "date": "2016-02-10",
         "tenk": "0001193125-15-056216", "tenk_url": "https://example.invalid/b.htm"}]))
    listed = calls.catalogue(path)
    # Newest first, and a call in April reports the first quarter.
    assert [c["ticker"] for c in listed] == ["NSIT", "EXPO"]
    assert listed[1]["period"] == "2015 Q1"
    assert listed[0]["period"] == "2015 Q4"
    assert listed[1]["accession"] == "0001144204-15-012949"


def test_no_prepared_calls_is_an_empty_list_not_an_error(tmp_path):
    assert calls.catalogue(tmp_path / "absent.json") == []


ROW = {"claim_id": "c1", "claim": "Revenue rose.", "speaker": "Person1", "segment": "prepared",
       "claim_type": "numerical_comparison", "metric": "revenue", "specificity": 5,
       "rhetorical_inflation": 0.0556, "evidence_gap": 1.0, "verdict": "contradicted",
       "parts": {"gap.hedging_delta": 0.5},
       "evidence": [{"agent": "xbrl-verifier", "tier": "structured", "stance": "contradicts",
                     "accession": "0001-15-1", "note": "filed 80293000 against stated 76100000"}]}


def test_a_contradicted_row_reads_as_overstated():
    ledger = calls.as_ledger("20150422_EXPO", [ROW], sentences=174)
    [claim] = ledger["claims"]
    assert claim["verdict"] == "overstated"
    assert claim["rhetoricalInflation"] == 5.6 and claim["evidenceGap"] == 100.0
    assert claim["evidence"][0]["span"].startswith("filed 80293000")
    assert ledger["evidenceItems"] == 1 and ledger["abstainRate"] == 0.0


def test_a_claim_nothing_was_found_for_carries_no_gap():
    row = {**ROW, "verdict": "abstain", "evidence_gap": None}
    [claim] = calls.as_ledger("c", [row], sentences=10)["claims"]
    assert claim["evidenceGap"] is None and claim["verdict"] == "abstain"


def test_no_probability_is_reported():
    ledger = calls.as_ledger("c", [ROW], sentences=10)
    assert ledger["calibrated"] is False
    assert all(c["probability"] is None for c in ledger["claims"])
