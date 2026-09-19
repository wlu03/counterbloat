from decimal import Decimal

import pytest

from backend.models import CalcInput, CalcStep, SourceSpan
from backend.verification.comparability import differences
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


def test_per_unit_evidence_differs_from_a_total_claim():
    claim = {"metric": "operational emissions", "period": "2025 vs 2024"}
    evidence = {"metric": "operational emissions", "denominator": "unit", "period": "2025 vs 2024"}
    assert differences(claim, evidence) == ["denominator"]
    assert differences(claim, {"metric": "operational emissions"}) == []
