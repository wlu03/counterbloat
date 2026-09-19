"""Execute a restricted list of arithmetic steps over source-linked inputs."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from backend.models import CalcInput, CalcStep, Calculation, SourceSpan

SAME_UNIT_OPS = {"add", "subtract", "sum", "compare", "pct_change", "reduction"}
OPS = SAME_UNIT_OPS | {"multiply", "divide"}


class CalculationError(Exception):
    pass


def parse_number(text: str) -> Decimal:
    try:
        return Decimal(text.replace(",", "").replace("%", "").strip())
    except InvalidOperation as exc:
        raise CalculationError(f"not a number: {text!r}") from exc


def value_in_source(value: Decimal, span: SourceSpan) -> bool:
    """True when the input's number appears in the span it cites."""
    numbers = re.findall(r"-?\d[\d,]*\.?\d*", span.text)
    return any(parse_number(n) == value for n in numbers)


def _unit_product(a: str, b: str) -> str:
    # "kg CO2e/unit" times "unit" is "kg CO2e". Other products keep both unit names.
    for rate, other in ((a, b), (b, a)):
        if "/" in rate:
            numerator, denominator = rate.rsplit("/", 1)
            if denominator.strip().rstrip("s") == other.strip().rstrip("s"):
                return numerator.strip()
    return f"{a}*{b}"


def execute(calc_id: str, claim_id: str, inputs: list[CalcInput], steps: list[CalcStep],
            note: str = "", lineage: list[str] | None = None) -> Calculation:
    values = {i.name: i.value for i in inputs}
    units = {i.name: i.unit for i in inputs}
    scope = {i.name: (i.population, i.boundary) for i in inputs}
    for step in steps:
        if step.op not in OPS:
            raise CalculationError(f"operation not allowed: {step.op}")
        missing = [a for a in step.args if a not in values]
        if missing or len(step.args) < 2:
            raise CalculationError(f"unknown or too few arguments: {step.args}")
        args = [values[a] for a in step.args]
        if step.op in SAME_UNIT_OPS:
            if len({units[a] for a in step.args}) > 1:
                raise CalculationError(f"incompatible units in {step.op}: "
                                       f"{[units[a] for a in step.args]}")
            scopes = {scope[a] for a in step.args if a in scope and any(scope[a])}
            if len(scopes) > 1:
                raise CalculationError(f"different population or boundary in {step.op}")
        x0, x1 = args[0], args[1]
        if step.op in ("add", "sum"):
            result, unit = sum(args, Decimal(0)), units[step.args[0]]
        elif step.op == "subtract":
            result, unit = x0 - x1, units[step.args[0]]
        elif step.op == "multiply":
            result, unit = x0 * x1, _unit_product(units[step.args[0]], units[step.args[1]])
        elif step.op == "divide":
            if x1 == 0:
                raise CalculationError("division by zero")
            same = units[step.args[0]] == units[step.args[1]]
            result, unit = x0 / x1, "ratio" if same else f"{units[step.args[0]]}/{units[step.args[1]]}"
        elif step.op == "pct_change":
            if x0 == 0:
                raise CalculationError("percentage change from zero")
            result, unit = (x1 - x0) / x0 * 100, "%"
        elif step.op == "reduction":
            if x0 <= 0:
                raise CalculationError("reduction needs a positive base")
            result, unit = (1 - x1 / x0) * 100, "%"
        else:  # compare: positive when the first value is larger
            result, unit = x0 - x1, units[step.args[0]]
        values[step.out], units[step.out] = result, unit
    outputs = {s.out: values[s.out] for s in steps}
    return Calculation(id=calc_id, claim_id=claim_id, inputs=inputs, steps=steps, outputs=outputs,
                       units={k: units[k] for k in outputs}, lineage=lineage or [], note=note)
