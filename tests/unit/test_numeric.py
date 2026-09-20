from decimal import Decimal

import pytest

from backend.models import CalcInput, CalcStep, SourceSpan
from backend.verification.numeric import CalculationError, execute, value_in_source


def _input(name, value, unit, period=None):
    return CalcInput(name=name, value=Decimal(value), unit=unit, period=period, source_span_id="s")


INPUTS = [_input("i24", "10", "kg CO2e/unit", "2024"), _input("i25", "6", "kg CO2e/unit", "2025"),
          _input("u24", "1000", "units", "2024"), _input("u25", "2000", "units", "2025")]
STEPS = [CalcStep(op="reduction", args=["i24", "i25"], out="intensity_reduction"),
         CalcStep(op="multiply", args=["i24", "u24"], out="e24"),
         CalcStep(op="multiply", args=["i25", "u25"], out="e25"),
         CalcStep(op="pct_change", args=["e24", "e25"], out="total_change")]


def test_worked_example_totals():
    calc = execute("c1", "claim", INPUTS, STEPS)
    assert calc.outputs["intensity_reduction"] == Decimal(40)
    assert calc.outputs["e24"] == Decimal(10000) and calc.outputs["e25"] == Decimal(12000)
    assert calc.outputs["total_change"] == Decimal(20)
    assert calc.units["e24"] == "kg CO2e" and calc.units["total_change"] == "%"


@pytest.mark.parametrize("steps", [
    [CalcStep(op="add", args=["i24", "u24"], out="x")],            # incompatible units
    [CalcStep(op="divide", args=["i24", "zero"], out="x")],        # zero denominator
    [CalcStep(op="pct_change", args=["zero", "i24"], out="x")],    # change from zero
    [CalcStep(op="eval", args=["i24", "i25"], out="x")],           # operation not allowed
    [CalcStep(op="add", args=["i24", "missing"], out="x")],        # input never supplied
])
def test_invalid_programs_are_rejected(steps):
    with pytest.raises(CalculationError):
        execute("c", "claim", INPUTS + [_input("zero", "0", "kg CO2e/unit")], steps)


def test_input_must_appear_in_its_source():
    span = SourceSpan(id="s", document_id="d", kind="table_row", start=0, end=1,
                      text="Units produced | 2024: 1,000 | 2025: 2,000")
    assert value_in_source(Decimal(1000), span)
    assert not value_in_source(Decimal(1500), span)


def test_a_change_computed_from_the_later_period_to_the_earlier_one_is_rejected():
    def value(name, number, period):
        return CalcInput(name=name, value=Decimal(number), unit="t", period=period, source_span_id="s")

    inputs = [value("a24", "10", "2024"), value("b24", "1000", "FY2024"),
              value("a25", "6", "2025"), value("b25", "2000", "2025")]
    totals = [CalcStep(op="add", args=["a24", "a24"], out="e24"),
              CalcStep(op="add", args=["a25", "a25"], out="e25")]
    forward = execute("n", "c", inputs, totals + [CalcStep(op="pct_change", args=["e24", "e25"], out="d")])
    assert forward.outputs["d"] == Decimal("-40")
    with pytest.raises(CalculationError, match="later period first"):
        execute("n", "c", inputs, totals + [CalcStep(op="pct_change", args=["e25", "e24"], out="d")])
    with pytest.raises(CalculationError, match="later period first"):
        execute("n", "c", inputs, [CalcStep(op="reduction", args=["a25", "b24"], out="d")])


def test_agreement_uses_the_precision_the_claim_is_written_with():
    from backend.verification.numeric import claim_relation

    outputs = {"x": Decimal("-39.6")}
    text = "We reduced emissions by 40% in 2025."
    for expected in ("-40", "-40.0", "-40.00"):
        assert claim_relation(outputs, "x", expected, text)[1] == "agrees"
    assert claim_relation(outputs, "x", "-40", "We reduced emissions by 40.0% in 2025.")[1] == "disagrees"
    assert claim_relation(outputs, "x", "-35", text) == (None, "none")  # 35 is not in the claim


def test_an_opposite_sign_of_the_same_size_does_not_count_as_disagreement():
    from backend.verification.numeric import claim_relation

    text = "We reduced emissions by 40% in 2025."
    assert claim_relation({"x": Decimal("-40")}, "x", "40", text) == (None, "none")
    assert claim_relation({"x": Decimal("40")}, "x", "-40", text) == (None, "none")
    assert claim_relation({"x": Decimal("20")}, "x", "-40", text)[1] == "disagrees"


def test_share_gives_a_part_as_a_percentage_of_its_whole():
    def value(name, number, population):
        return CalcInput(name=name, value=Decimal(number), unit="managers", period="2024",
                         population=population, source_span_id="s")

    inputs = [value("women", "58", "women"), value("everyone", "200", "all managers")]
    result = execute("n", "c", inputs, [CalcStep(op="share", args=["women", "everyone"], out="pct")])
    assert result.outputs["pct"] == Decimal("29") and result.units["pct"] == "%"
    margins = [CalcInput(name=n, value=Decimal(v), unit="EUR million", period=p, source_span_id="s")
               for n, v, p in (("p24", "60", "2024"), ("r24", "600", "2024"),
                               ("p25", "90", "2025"), ("r25", "720", "2025"))]
    points = execute("n", "c", margins, [CalcStep(op="share", args=["p24", "r24"], out="m24"),
                                         CalcStep(op="share", args=["p25", "r25"], out="m25"),
                                         CalcStep(op="subtract", args=["m25", "m24"], out="change")])
    assert points.outputs["change"] == Decimal("2.5") and points.units["change"] == "%"
    with pytest.raises(CalculationError, match="zero whole"):
        execute("n", "c", [value("a", "1", None), value("b", "0", None)],
                [CalcStep(op="share", args=["a", "b"], out="x")])


def test_parts_with_different_populations_can_be_added_but_not_compared():
    def value(name, number, period, population):
        return CalcInput(name=name, value=Decimal(number), unit="injuries", period=period,
                         population=population, source_span_id="s")

    inputs = [value("east23", "50", "2023", "Eastmere"), value("west23", "40", "2023", "Corbank"),
              value("east25", "30", "2025", "Eastmere"), value("west25", "42", "2025", "Corbank")]
    total = execute("n", "c", inputs, [CalcStep(op="sum", args=["east23", "west23"], out="all23"),
                                       CalcStep(op="sum", args=["east25", "west25"], out="all25"),
                                       CalcStep(op="pct_change", args=["all23", "all25"], out="change")])
    assert total.outputs["change"] == Decimal("-20")
    with pytest.raises(CalculationError, match="different population"):
        execute("n", "c", inputs, [CalcStep(op="pct_change", args=["east23", "west25"], out="x")])


def test_a_figure_is_read_as_a_document_writes_it():
    from backend.verification.numeric import parse_number

    assert parse_number("$ 50") == parse_number("$50") == parse_number("50") == Decimal(50)
    assert parse_number("US$ 1,234.5") == Decimal("1234.5")
    # A filing writes a negative in brackets, and FinQA's tables write it twice.
    assert parse_number("(32)") == parse_number("( 32 )") == Decimal(-32)
    assert parse_number("-32 ( 32 )") == Decimal(-32)
    assert parse_number("12.5%") == Decimal("12.5")
    with pytest.raises(CalculationError):
        parse_number("about fifty")


def test_a_table_writes_a_negative_in_brackets_so_only_the_negative_is_in_it():
    span = SourceSpan(id="s", document_id="d", kind="table_row", start=0, end=40,
                      text="waterford 3 replacement steam generator provision | amount: -32 ( 32 )")
    assert value_in_source(Decimal(-32), span)
    # Reading the bracketed form as a positive would let a program flip a sign without saying so.
    assert not value_in_source(Decimal(32), span)


def test_a_range_dash_is_not_a_minus_sign_but_a_currency_symbol_may_be_spaced():
    def span(text):
        return SourceSpan(id="s", document_id="d", kind="table_row", start=0, end=len(text),
                          text=text)

    # "39 - 40" is a range of useful lives, so it holds 39 and 40 and not -40.
    lives = span("buildings | useful life in years: 39 - 40")
    assert value_in_source(Decimal(39), lives) and value_in_source(Decimal(40), lives)
    assert not value_in_source(Decimal(-40), lives)
    # A filing puts a space after the currency symbol, and writes a negative with none.
    assert value_in_source(Decimal(772), span("commercial mortgages | 2012: $ 772"))
    assert value_in_source(Decimal(-32), span("provision | amount: -32"))


def test_a_bracketed_amount_in_a_table_is_negative_and_in_a_sentence_may_not_be():
    where = dict(id="s", document_id="d", start=0, end=40, text="Capital expenditure: (1,577).")
    table = SourceSpan(kind="table_row", **where)
    assert value_in_source(Decimal(-1577), table) and not value_in_source(Decimal(1577), table)
    # Outside a table the brackets may hold an aside rather than an accounting negative.
    sentence = SourceSpan(kind="paragraph", **where)
    assert value_in_source(Decimal(-1577), sentence) and value_in_source(Decimal(1577), sentence)


def test_a_step_may_name_a_scale_factor_but_no_other_number():
    def value(name, number, unit):
        return CalcInput(name=name, value=Decimal(number), unit=unit, source_span_id="s")

    # FinQA's own programs convert to millions this way: multiply(1211143, 308.10) / const_1000000.
    shares = [value("count", "1211143", "shares"), value("price", "308.10", "USD/share")]
    result = execute("n", "c", shares, [CalcStep(op="multiply", args=["count", "price"], out="total"),
                                        CalcStep(op="divide", args=["total", "const_1000000"], out="millions")])
    assert result.outputs["millions"] == Decimal("373.153158300")
    # Dividing by a scale factor changes the scale, not the unit.
    assert result.units["millions"] == result.units["total"] == "USD"
    with pytest.raises(CalculationError, match="unknown or too few arguments"):
        execute("n", "c", shares, [CalcStep(op="divide", args=["count", "const_7"], out="x")])
    # An input of the same name is a document figure and wins over the factor.
    own = [value("const_1000", "42", "t"), value("other", "2", "t")]
    assert execute("n", "c", own, [CalcStep(op="add", args=["const_1000", "other"], out="s")]).outputs["s"] == 44


def test_a_scale_factor_can_be_added_to_a_value_but_two_real_units_still_cannot():
    def value(name, number, unit):
        return CalcInput(name=name, value=Decimal(number), unit=unit, source_span_id="s")

    # The growth idiom: revenue divided by (1 + growth) recovers the earlier year.
    inputs = [value("rev17", "6.22", "billion dollars"), value("growth", "7", "percent")]
    steps = [CalcStep(op="divide", args=["growth", "const_100"], out="fraction"),
             CalcStep(op="add", args=["const_1", "fraction"], out="factor"),
             CalcStep(op="divide", args=["rev17", "factor"], out="rev16")]
    result = execute("n", "c", inputs, steps)
    assert result.outputs["rev16"].quantize(Decimal("0.001")) == Decimal("5.813")
    with pytest.raises(CalculationError, match="incompatible units in add"):
        execute("n", "c", [value("a", "1", "tonnes"), value("b", "2", "kg")],
                [CalcStep(op="add", args=["a", "b"], out="x")])


def test_a_claim_that_states_a_bound_is_judged_against_the_bound_not_for_equality():
    from backend.verification.numeric import claim_relation

    def relation(result, expected, text):
        return claim_relation({"x": Decimal(result)}, "x", expected, text)[1]

    # A result that clears the bound agrees with it. Testing for equality would call it false.
    assert relation("60", "40", "Revenue increased by at least 40%.") == "agrees"
    assert relation("38", "40", "Revenue increased by at least 40%.") == "disagrees"
    assert relation("2", "5", "The error rate is below 5%.") == "agrees"
    assert relation("7", "5", "The error rate is below 5%.") == "disagrees"
    assert relation("3", "5", "We emit no more than 5 tonnes.") == "agrees"
    assert relation("120", "100", "Savings of $100 million or more.") == "agrees"
    # A bound is read only beside the number it bounds, so a period does not become one.
    assert relation("12", "12", "Over the past year revenue rose 12%.") == "agrees"
    # Two endpoints do not say which one a single result should meet.
    assert relation("50", "40", "Growth was between 40% and 45%.") == "none"
    # The claim writes a fall as a positive number and the calculation as a negative one. Which
    # convention the bound uses is not stated.
    assert relation("-45", "40", "Emissions fell by more than 40%.") == "none"
    # A claim that states a plain value is still judged to the precision it was written with.
    assert relation("41.8", "42", "Emissions fell 42% from 2019.") == "agrees"
    assert relation("30", "42", "Emissions fell 42% from 2019.") == "disagrees"


def test_a_scale_factor_does_not_strip_the_period_or_population_of_what_it_scales():
    def value(name, number, **about):
        return CalcInput(name=name, value=Decimal(number), unit="t", source_span_id="s", **about)

    # Converting units before a comparison must not hide that the two values are different plants.
    plants = [value("pa", "10", population="Plant A"), value("pb", "20", population="Plant B")]
    scaled = [CalcStep(op="multiply", args=["pa", "const_1"], out="ca"),
              CalcStep(op="multiply", args=["pb", "const_1"], out="cb"),
              CalcStep(op="compare", args=["ca", "cb"], out="d")]
    with pytest.raises(CalculationError, match="different population or boundary"):
        execute("n", "c", plants, scaled)
    # Nor that the years were given to pct_change in the wrong order.
    years = [value("y24", "100", period="2024"), value("y25", "120", period="2025")]
    with pytest.raises(CalculationError, match="later period first"):
        execute("n", "c", years, [CalcStep(op="multiply", args=["y25", "const_1"], out="c25"),
                                  CalcStep(op="multiply", args=["y24", "const_1"], out="c24"),
                                  CalcStep(op="pct_change", args=["c25", "c24"], out="d")])


def test_two_programs_over_the_same_numbers_are_the_same_only_if_wired_the_same():
    from backend.models import RunManifest
    from backend.orchestration.worker import _calculations
    from backend.providers.base import EvidenceAnalysis, InputDraft, ProgramDraft

    span = SourceSpan(id="s", document_id="d", kind="paragraph", start=0, end=40,
                      text="Revenue was 100 and cost was 50.")
    state = _state_for_calculations()

    def program(over, under, out):
        return ProgramDraft(
            inputs=[_draft("a", "100"), _draft("b", "50")],
            steps=[CalcStep(op="divide", args=[over, under], out=out)],
            claim_output=out, claim_expected="2", note="")

    manifest = RunManifest(analysis_id="a", mode="live", config_hash="h")
    both = _calculations(EvidenceAnalysis(judgments=[], answers=[],
                                          programs=[program("a", "b", "over"),
                                                    program("b", "a", "under")]),
                         state, {"s": span}, manifest)
    # a over b is 2 and b over a is 0.5. Treating them as one calculation would drop one result.
    assert sorted(c.outputs[c.claim_output] for c in both) == [Decimal("0.5"), Decimal(2)]

    # A program that fails does not reserve the numbers it read against a later, valid program.
    manifest = RunManifest(analysis_id="a", mode="live", config_hash="h")
    broken = program("a", "b", "x")
    broken.steps = [CalcStep(op="divide", args=["a", "missing"], out="x")]
    after = _calculations(EvidenceAnalysis(judgments=[], answers=[],
                                           programs=[broken, program("a", "b", "x")]),
                          state, {"s": span}, manifest)
    assert [c.outputs["x"] for c in after] == [Decimal(2)]
    assert any("calculation rejected" in r for r in manifest.rejections)

    # The same arithmetic offered against a different stated value is a second reading of the
    # claim, so it is kept. Offered against the same value again, it is a repeat.
    manifest = RunManifest(analysis_id="a", mode="live", config_hash="h")
    other = program("a", "b", "x")
    other.claim_expected = "3"
    readings = _calculations(EvidenceAnalysis(judgments=[], answers=[],
                                              programs=[program("a", "b", "x"), other,
                                                        program("a", "b", "x")]),
                             state, {"s": span}, manifest)
    assert [c.claim_relation for c in readings] == ["agrees", "disagrees"]
    assert sum("repeating one already recorded" in r for r in manifest.rejections) == 1


def _draft(name, value):
    from backend.providers.base import InputDraft

    return InputDraft(name=name, value=value, unit="USD", period=None, population=None,
                      boundary=None, source_span_id="s")


def _state_for_calculations():
    from backend.models import AssertionType, Claim, InvestigationState

    text = "Revenue was 2 times cost, not 3 times."
    claim = Claim(id="c", document_id="d", span_id="s0", text=text, start=0, end=len(text),
                  assertion_type=AssertionType.numerical_comparison)
    return InvestigationState(claim=claim)
