from decimal import Decimal

import pytest

from backend.models import AssertionType, Claim, Relationship
from backend.verification import xbrl


def _claim(**fields):
    return Claim(id="c1", document_id="d", span_id="s", text=fields.pop("text", "x"),
                 start=0, end=1, assertion_type=AssertionType.numerical_comparison, **fields)


def _facts(monkeypatch, rows):
    monkeypatch.setattr(xbrl, "facts", lambda cik, tag, unit="USD":
                        rows.get(tag, []))


def test_wording_outside_the_table_is_not_guessed_at():
    assert xbrl.tag_for("net revenues")[0].startswith("RevenueFromContract")
    assert xbrl.tag_for("synergy capture") == ()
    assert xbrl.tag_for(None) == ()


def test_a_value_is_scaled_once():
    assert xbrl.stated_value(_claim(value="$76.1 million", unit="USD millions")) == Decimal("76100000")
    assert xbrl.stated_value(_claim(value="76.1", unit="USD millions")) == Decimal("76100000")
    assert xbrl.stated_value(_claim(value="$0.75", unit="USD per share")) == Decimal("0.75")
    assert xbrl.stated_value(_claim(value="strong growth")) is None


def test_a_filed_value_within_the_spoken_precision_supports_the_claim(monkeypatch):
    _facts(monkeypatch, {"Revenues": [
        {"end": "2015-03-31", "start": "2015-01-01", "val": 76_080_000, "accn": "0001-15-1"}]})
    check = xbrl.verify(_claim(metric="revenue", value="$76.1 million", unit="USD millions",
                               period="2015-Q1"), "0000012345")
    # 76.1 was said to one decimal, so anything within 50,000 agrees.
    assert check.stance == xbrl.SUPPORTS
    assert check.relationship is Relationship.supports
    assert check.accession == "0001-15-1"


def test_a_filed_value_outside_that_precision_contradicts_it(monkeypatch):
    _facts(monkeypatch, {"Revenues": [
        {"end": "2015-03-31", "start": "2015-01-01", "val": 71_000_000, "accn": "0001-15-1"}]})
    check = xbrl.verify(_claim(metric="revenue", value="$76.1 million", unit="USD millions",
                               period="2015-Q1"), "0000012345")
    assert check.stance == xbrl.CONTRADICTS
    assert check.filed == Decimal("71000000") and check.stated == Decimal("76100000")


def test_a_period_the_company_did_not_file_is_not_found(monkeypatch):
    _facts(monkeypatch, {"Revenues": [
        {"end": "2019-03-31", "start": "2019-01-01", "val": 76_100_000, "accn": "x"}]})
    check = xbrl.verify(_claim(metric="revenue", value="$76.1 million", period="2015-Q1"),
                        "0000012345")
    assert check.stance == xbrl.NOT_FOUND and check.tag is None


def test_a_claim_with_no_number_is_not_found(monkeypatch):
    _facts(monkeypatch, {})
    check = xbrl.verify(_claim(metric="revenue", value="up nicely"), "0000012345")
    assert check.stance == xbrl.NOT_FOUND
    assert "no number" in check.note


def test_a_company_defined_measure_is_not_checked_against_the_filed_total(monkeypatch):
    _facts(monkeypatch, {"Revenues": [
        {"end": "2015-03-31", "start": "2015-01-01", "val": 80_293_000, "accn": "x"}]})
    check = xbrl.verify(_claim(metric="revenues before reimbursements (net revenues)",
                               text="revenues before reimbursements were $76.1 million",
                               value="$76.1 million", period="2015-Q1"), "0000012345")
    assert check.stance == xbrl.NOT_FOUND
    assert "company-defined" in check.note


def test_a_forward_looking_claim_has_nothing_filed_to_check(monkeypatch):
    _facts(monkeypatch, {"CommonStockDividendsPerShareDeclared": [
        {"end": "2015-03-31", "start": "2015-01-01", "val": 0.30, "accn": "x"}]})
    claim = Claim(id="c1", document_id="d", span_id="s", text="our quarterly dividend will change",
                  start=0, end=1, assertion_type=AssertionType.future_target,
                  metric="quarterly dividend", value="$0.15", period="2015-Q1")
    check = xbrl.verify(claim, "0000012345")
    assert check.stance == xbrl.NOT_FOUND and "future" in check.note


def test_an_annual_figure_cannot_answer_a_quarterly_claim(monkeypatch):
    _facts(monkeypatch, {"Revenues": [
        {"end": "2015-03-31", "start": "2014-04-01", "val": 76_100_000, "accn": "x"}]})
    check = xbrl.verify(_claim(metric="revenue", value="$76.1 million", period="2015-Q1"),
                        "0000012345")
    assert check.stance == xbrl.NOT_FOUND


def test_the_amount_is_taken_over_the_rate_of_change():
    # Only one of these is written as money, and that is what a filed figure answers.
    assert xbrl.stated_value(_claim(value="13% increase; $10.3 million")) == Decimal("10300000")
    assert xbrl.stated_value(_claim(value="up 4% to 73 million")) == Decimal("73000000")
    # The same number written twice is not ambiguous.
    assert xbrl.stated_value(_claim(value="$10.3 million, or 10.3")) == Decimal("10300000")


def test_two_amounts_in_one_value_are_still_not_guessed_at():
    assert xbrl.stated_value(_claim(value="$10.3 million versus $9.1 million")) is None
    assert xbrl.stated_value(_claim(value="grew 13% from 4%")) is None


def test_a_claim_with_no_period_is_not_compared_with_the_newest_figure(monkeypatch):
    _facts(monkeypatch, {"NetIncomeLoss": [
        {"end": "2025-12-31", "start": "2025-01-01", "val": 38_640_000, "accn": "new"},
        {"end": "2015-04-03", "start": "2015-01-03", "val": 10_333_000, "accn": "old"}]})
    claim = _claim(metric="net income", value="$10.3 million")
    assert xbrl.verify(claim, "0000012345").stance == xbrl.NOT_FOUND
    # Given the period of the call, the right figure is found.
    found = xbrl.verify(claim, "0000012345", period="2015-Q1")
    assert found.stance == xbrl.SUPPORTS and found.accession == "old"
