"""Execute a restricted list of arithmetic steps over source-linked inputs."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from backend.models import CalcInput, CalcStep, Calculation, SourceSpan

SAME_UNIT_OPS = {"add", "subtract", "sum", "compare", "pct_change", "reduction", "share"}
OPS = SAME_UNIT_OPS | {"multiply", "divide"}
# Operations that compare two values of one measure. Both values must cover the same population
# and boundary. Adding parts to a total, or taking a part as a share of its whole, does not.
SAME_SCOPE_OPS = {"compare", "pct_change", "reduction"}
# Scale factors a step may name. They convert a unit, such as dollars to millions of dollars, and
# they carry no unit of their own. They are not figures read from a document, so they need no
# source, and the list is fixed so a program cannot introduce a value of its own this way.
CONSTANTS = {"const_1": Decimal(1), "const_10": Decimal(10), "const_100": Decimal(100),
             "const_1000": Decimal(1000), "const_1000000": Decimal(1_000_000),
             "const_1000000000": Decimal(1_000_000_000)}


class CalculationError(Exception):
    pass


_CURRENCY = re.compile(r"(?:US|C|A|HK)?[$€£¥]")


def parse_number(text: str) -> Decimal:
    """Read a figure as a document writes it.

    A filing puts the currency symbol beside the number and writes a negative in brackets.
    FinQA's tables write a negative twice, as "-32 ( 32 )", where the first form is signed.
    """
    cleaned = _CURRENCY.sub("", text).replace(",", "").replace("%", "").strip()
    written, negative = cleaned.split("(")[0].strip(), False
    if not written and cleaned.startswith("(") and cleaned.rstrip().endswith(")"):
        written, negative = cleaned.strip()[1:-1].strip(), True
    try:
        value = Decimal(written)
    except InvalidOperation as exc:
        raise CalculationError(f"not a number: {text!r}") from exc
    return -value if negative else value


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
    if not a or not b:
        return a or b  # multiplying by a scale factor changes the scale, not the unit
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
    for name, factor in CONSTANTS.items():
        # An input of the same name wins, so a document figure is never shadowed by a constant.
        values.setdefault(name, factor)
        units.setdefault(name, "")
        scope.setdefault(name, (None, None))
        periods.setdefault(name, None)
    for step in steps:
        if step.op not in OPS:
            raise CalculationError(f"operation not allowed: {step.op}")
        missing = [a for a in step.args if a not in values]
        if missing or len(step.args) < 2:
            raise CalculationError(f"unknown or too few arguments: {step.args}")
        args = [values[a] for a in step.args]
        if step.op in SAME_UNIT_OPS:
            # A scale factor carries no unit and takes the unit of what it is combined with, so
            # "1 + growth" is allowed. Two figures that do carry units must still agree.
            named = {units[a] for a in step.args if units[a]}
            shared_unit = next(iter(named), "")
            if len(named) > 1:
                raise CalculationError(f"incompatible units in {step.op}: "
                                       f"{[units[a] for a in step.args]}")
            scopes = {scope[a] for a in step.args if a in scope and any(scope[a])}
            if len(scopes) > 1 and step.op in SAME_SCOPE_OPS:
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
            result, unit = sum(args, Decimal(0)), shared_unit
        elif step.op == "subtract":
            result, unit = x0 - x1, shared_unit
        elif step.op == "multiply":
            first, second = periods.get(step.args[0]), periods.get(step.args[1])
            if first and second and first != second:
                raise CalculationError(f"different periods in multiply: {first}, {second}")
            result, unit = x0 * x1, _unit_product(units[step.args[0]], units[step.args[1]])
        elif step.op == "divide":
            if x1 == 0:
                raise CalculationError("division by zero")
            over, under = units[step.args[0]], units[step.args[1]]
            # Dividing by a scale factor changes the scale, not the unit.
            result = x0 / x1
            unit = over if not under else "ratio" if over == under else f"{over}/{under}"
        elif step.op == "pct_change":
            if x0 == 0:
                raise CalculationError("percentage change from zero")
            result, unit = (x1 - x0) / x0 * 100, "%"
        elif step.op == "share":
            if x1 == 0:
                raise CalculationError("share of a zero whole")
            result, unit = x0 / x1 * 100, "%"  # the first value as a percentage of the second
        elif step.op == "reduction":
            if x0 <= 0:
                raise CalculationError("reduction needs a positive base")
            result, unit = (1 - x1 / x0) * 100, "%"
        else:  # compare: positive when the first value is larger
            result, unit = x0 - x1, shared_unit
        values[step.out], units[step.out] = result, unit
    outputs = {s.out: values[s.out] for s in steps}
    return Calculation(id=calc_id, claim_id=claim_id, inputs=inputs, steps=steps, outputs=outputs,
                       units={k: units[k] for k in outputs}, lineage=lineage or [], note=note)
