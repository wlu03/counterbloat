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
    # A hyphen after a word character is a range dash, so "5-10" holds 5 and 10, not -10.
    numbers = re.findall(r"(?<!\w)-?\d[\d,]*\.?\d*|\d[\d,]*\.?\d*", span.text)
    return any(parse_number(n) == value for n in numbers)


def _words(unit: str) -> set[str]:
    return {word.rstrip("s") for word in re.findall(r"[a-z0-9]+", unit.lower())}


def _unit_product(a: str, b: str) -> str:
    # "kg CO2e/unit" times "unit" or "units produced" is "kg CO2e": every word of the rate's
    # denominator appears in the other unit. A rate times any other unit is rejected.
    for rate, other in ((a, b), (b, a)):
        if "/" in rate:
            numerator, denominator = rate.rsplit("/", 1)
            if _words(denominator) and _words(denominator) <= _words(other):
                return numerator.strip()
    if "/" in a or "/" in b:
        raise CalculationError(f"incompatible units in multiply: {a}, {b}")
    return f"{a}*{b}"


def _year(period: str | None) -> int | None:
    found = re.fullmatch(r"\D*((?:19|20)\d{2})\D*", period or "")
    return int(found.group(1)) if found else None


def claim_relation(outputs: dict[str, Decimal], claim_output: str | None,
                   claim_expected: str | None, claim_text: str) -> tuple[Decimal | None, str]:
    """Compare the named output with the value the claim states.

    The expected value must be a number written in the claim. Agreement is judged to the
    precision of that number, so a stated 40 agrees with 39.6 and not with 38.
    """
    if not claim_output or claim_output not in outputs or not claim_expected:
        return None, "none"
    try:
        expected = parse_number(claim_expected)
    except CalculationError:
        return None, "none"
    written = [n for n in re.findall(r"\d[\d,]*\.?\d*", claim_text)
               if abs(parse_number(n)) == abs(expected)]
    if not written:
        return None, "none"
    # The precision comes from the claim's own wording, not from how the model wrote the value.
    tolerance = Decimal(1).scaleb(int(parse_number(written[0]).as_tuple().exponent)) / 2
    result = outputs[claim_output]
    if abs(result - expected) <= tolerance:
        return expected, "agrees"
    if abs(abs(result) - abs(expected)) <= tolerance:
        # Same size, opposite sign: the model wrote a fall as a positive number or the reverse.
        # The sign convention is not known, so the calculation does not test the claim.
        return None, "none"
    return expected, "disagrees"


def execute(calc_id: str, claim_id: str, inputs: list[CalcInput], steps: list[CalcStep],
            note: str = "", lineage: list[str] | None = None) -> Calculation:
    values = {i.name: i.value for i in inputs}
    units = {i.name: i.unit for i in inputs}
    scope = {i.name: (i.population, i.boundary) for i in inputs}
    periods = {i.name: i.period for i in inputs}
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
        shared = {periods.get(a) for a in step.args}
        # A result of values from one period belongs to that period.
        periods[step.out] = shared.pop() if len(shared) == 1 else None
        if step.op in ("pct_change", "reduction"):
            base, later = (_year(periods.get(a)) for a in step.args[:2])
            if base and later and base > later:
                # The first argument is the base. A later base reverses the sign and the ratio.
                raise CalculationError(f"{step.op} has the later period first: {base}, {later}")
        if step.op in ("add", "sum"):
            result, unit = sum(args, Decimal(0)), units[step.args[0]]
        elif step.op == "subtract":
            result, unit = x0 - x1, units[step.args[0]]
        elif step.op == "multiply":
            first, second = periods.get(step.args[0]), periods.get(step.args[1])
            if first and second and first != second:
                raise CalculationError(f"different periods in multiply: {first}, {second}")
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
