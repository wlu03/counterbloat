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


# A number as a document writes it, including the bracketed form a table uses for a negative.
# A hyphen after a word character is a range dash, so "5-10" holds 5 and 10, not -10.
# A space may follow a currency symbol but never the sign, so the range "39 - 40" holds 39 and
# 40 and not -40.
_IN_SOURCE = re.compile(r"\(\s*(?:US|C|A|HK)?[$€£¥]?\s*\d[\d,]*\.?\d*\s*%?\s*\)"
                        r"|(?<!\w)-?(?:(?:US|C|A|HK)?[$€£¥]\s*)?\d[\d,]*\.?\d*")


def value_in_source(value: Decimal, span: SourceSpan) -> bool:
    """True when the input's number appears in the span it cites.

    A table writes a negative in brackets, so "(1,577)" is the value -1577 and not 1577. In
    running text brackets usually hold an aside, so there both readings are accepted; only the
    same tokenizer that `parse_number` uses decides what the digits mean.
    """
    for written in _IN_SOURCE.findall(span.text):
        try:
            found = parse_number(written)
        except CalculationError:
            continue
        if found == value:
            return True
        # Outside a table a bracketed number may be an aside rather than a negative.
        if span.kind != "table_row" and found < 0 and written.strip().startswith("(") and -found == value:
            return True
    return False


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


# Wordings that state a bound instead of a value. "At least 40%" is not the claim that the figure
# is 40%, so testing it for equality reads a satisfied bound as a contradiction.
_BEFORE = {"no less than": "ge", "not less than": "ge", "at least": "ge", "a minimum of": "ge",
           "minimum of": "ge", "more than": "gt", "greater than": "gt", "over": "gt",
           "above": "gt", "exceeds": "gt", "exceeded": "gt", "exceeding": "gt", "exceed": "gt",
           "no more than": "le", "not more than": "le", "at most": "le", "a maximum of": "le",
           "maximum of": "le", "up to": "le", "within": "le",
           "less than": "lt", "fewer than": "lt", "under": "lt", "below": "lt", "beneath": "lt"}
_AFTER = {"more": "ge", "higher": "ge", "greater": "ge", "above": "ge",
          "less": "le", "fewer": "le", "lower": "le", "below": "le"}
# A bound counts only next to the number it bounds. Anything between the two may be a hedge or a
# currency sign, so "over the past year revenue rose 12%" states no bound and "over $40" does.
_BOUND_BEFORE = re.compile(
    r"\b(" + "|".join(sorted(_BEFORE, key=len, reverse=True)).replace(" ", r"\s+") + r")\s+"
    r"(?:about|approximately|roughly|nearly|almost|around|some|another)?\s*"
    r"(?:US|C|A|HK)?[$€£¥]?\s*$", re.I)
# The same next to the number, allowing the unit and scale that follow it: "$100 million or more".
_BOUND_AFTER = re.compile(r"^[\s%]*(?:[A-Za-z]+\s+){0,3}or\s+(" + "|".join(_AFTER) + r")\b", re.I)
# Two endpoints, not one value. Which endpoint a single result should be tested against is not
# stated, so the calculation does not test the claim.
_RANGE = re.compile(r"\b(?:between|range|ranging|from)\b[^.]{0,40}$", re.I)
_SATISFIES = {"ge": lambda r, e, t: r >= e - t, "gt": lambda r, e, t: r > e - t,
              "le": lambda r, e, t: r <= e + t, "lt": lambda r, e, t: r < e + t}


def _bound(claim_text: str, at: int, length: int) -> str | None:
    """The comparator the claim applies to the number at this position, or None for a plain value."""
    before, after = claim_text[:at], claim_text[at + length:]
    if _RANGE.search(before):
        return "range"
    found = _BOUND_BEFORE.search(before)
    if found:
        return _BEFORE[re.sub(r"\s+", " ", found.group(1).lower())]
    found = _BOUND_AFTER.search(after)
    return _AFTER[found.group(1).lower()] if found else None


def claim_relation(outputs: dict[str, Decimal], claim_output: str | None,
                   claim_expected: str | None, claim_text: str) -> tuple[Decimal | None, str]:
    """Compare the named output with the value the claim states.

    The expected value must be a number written in the claim. A claim that states a plain value is
    judged to the precision of that number, so a stated 40 agrees with 39.6 and not with 38. A
    claim that states a bound, such as "at least 40%", is judged by whether the result meets the
    bound. Where the contract is not clear, the result is "none" and the calculation does not test
    the claim.
    """
    if not claim_output or claim_output not in outputs or not claim_expected:
        return None, "none"
    try:
        expected = parse_number(claim_expected)
    except CalculationError:
        return None, "none"
    written = [m for m in re.finditer(r"\d[\d,]*\.?\d*", claim_text)
               if abs(parse_number(m.group())) == abs(expected)]
    if not written:
        return None, "none"
    # The precision comes from the claim's own wording, not from how the model wrote the value.
    here = written[0]
    tolerance = Decimal(1).scaleb(int(parse_number(here.group()).as_tuple().exponent)) / 2
    result, bound = outputs[claim_output], _bound(claim_text, here.start(), len(here.group()))
    if bound == "range":
        return None, "none"
    if bound:
        if (result < 0) != (expected < 0) and result and expected:
            # A fall written as a negative number and a bound written as a positive one. Which
            # convention the bound uses is not stated, so the calculation does not test it.
            return None, "none"
        return expected, "agrees" if _SATISFIES[bound](result, expected, tolerance) else "disagrees"
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
        # A result of values from one period belongs to that period. A scale factor has no period
        # of its own, so it does not erase the period of the value it scales.
        dated = {periods.get(a) for a in step.args if periods.get(a)}
        periods[step.out] = dated.pop() if len(dated) == 1 else None
        # The same for population and boundary, so a derived value can still be compared.
        named = {scope[a] for a in step.args if a in scope and any(scope[a])}
        scope[step.out] = named.pop() if len(named) == 1 else (None, None)
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
