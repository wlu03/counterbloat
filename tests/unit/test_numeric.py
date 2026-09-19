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
