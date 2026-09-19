"""Score one arm's output for one case. Every check is done by code against the case's documents."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from backend.models import SourceSpan
from evaluation.comparison.schema import AuditOutput, Case

TOLERANCE = Decimal("0.05")
RATIO_UNITS = {"ratio", "fraction", "share", "proportion"}
_IDS = re.compile(r"doc-[0-9a-f]{16}(?:-s\d+)?")  # passage ids contain digits that are not figures


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _numbers(text: str) -> list[Decimal]:
    return [Decimal(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", text)]


def _decimal(text: str) -> Decimal | None:
    try:
        return Decimal(re.sub(r"[^0-9.\-]", "", text))
    except InvalidOperation:
        return None


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(abs(a) - abs(b)) <= TOLERANCE


def _forms(number) -> list[Decimal]:
    """A key number is written in percent. A share given as a fraction of 1 is the same result."""
    value = _decimal(number.value)
    if value is None:
        return []
    return [value, value * 100] if number.unit.strip().casefold() in RATIO_UNITS else [value]


def _covered(quote: str, wanted: str) -> float:
    """Share of the wanted claim text that the quote reproduces as one run of characters."""
    match = SequenceMatcher(None, quote, wanted, autojunk=False).find_longest_match()
    return match.size / len(wanted)


def score(case: Case, passages: dict[str, list[SourceSpan]], output: AuditOutput) -> dict:
    expected = case.expected
    wanted = _squash(expected.claim_contains)
    keys = [k for k in map(_decimal, expected.key_numbers) if k is not None]
    # The finding about the case's claim is the one whose quote covers most of the claim text.
    # A quote that starts or ends elsewhere in the same sentence still counts.
    ranked = sorted(output.findings, key=lambda f: _covered(_squash(f.claim_quote), wanted),
                    reverse=True)
    finding = ranked[0] if ranked and _covered(_squash(ranked[0].claim_quote), wanted) >= 0.6 else None
    result = {"claim_found": finding is not None, "status": finding.status if finding else None,
              "status_correct": bool(finding) and finding.status in expected.accept_statuses,
              "other_findings": len(output.findings) - (1 if finding else 0),
              "key_numbers": len(keys), "key_numbers_found": 0}
    if finding is None:
        return result
    texts = {d: [_squash(s.text) for s in spans] for d, spans in passages.items()}
    everything = [t for spans in texts.values() for t in spans]
    # A quote counts when it is an exact substring of a passage of the document it names. When
    # the named document is not one of the supplied ones, every supplied passage is searched.
    exact = [any(_squash(q.quote) in t for t in texts.get(q.document_id, everything))
             for q in finding.evidence if q.quote.strip()]
    stated = _numbers(_IDS.sub(" ", f"{finding.summary} {finding.supported_rewrite or ''}"))
    computed = [v for n in finding.computed for v in _forms(n)]
    in_documents = [n for t in everything for n in _numbers(t)]
    reference = [v for v in map(_decimal, expected.derived_numbers + expected.key_numbers)
                 if v is not None]
    allowed = in_documents + reference + [v / 100 for v in reference]

    def reached(key: Decimal) -> bool:
        # A key number counts when it was calculated. In the text it counts only when it is a
        # number the documents do not contain, because restating the claim is not a calculation.
        written = not any(_close(key, n) for n in in_documents)
        return any(_close(key, n) for n in computed) or (written and any(_close(key, n) for n in stated))

    result.update(
        quotes=len(exact), quotes_exact=sum(exact),
        key_numbers_found=sum(map(reached, keys)),
        # Numbers in the text that are in no passage and not among the reference calculations.
        # They may be correct arithmetic the reference did not list, so they are listed, not judged.
        unverified_numbers=sorted({str(n) for n in stated if not any(_close(n, a) for a in allowed)}),
        probability_stated=finding.probability is not None)
    return result


def summarise(rows: list[dict]) -> dict:
    """Totals for one arm. Rates leave out cases in which the arm did not run."""
    ran = [r for r in rows if r.get("error") is None]

    def rate(top: str, bottom: str | None = None) -> float | None:
        total = sum(r.get(bottom, 0) for r in ran) if bottom else len(ran)
        return sum(r.get(top, 0) for r in ran) / total if total else None

    by_case: dict[str, set] = {}
    for r in ran:
        by_case.setdefault(r["case"], set()).add(r.get("status"))
    repeated = [statuses for case, statuses in by_case.items()
                if sum(r["case"] == case for r in ran) > 1]
    return {"cases_run": len(ran), "cases_failed": len(rows) - len(ran),
            "claim_found": rate("claim_found"), "status_correct": rate("status_correct"),
            "key_numbers_found": rate("key_numbers_found", "key_numbers"),
            "quotes_exact": rate("quotes_exact", "quotes"),
            "findings_without_a_quote": sum(r.get("quotes") == 0 for r in ran),
            "unverified_numbers": sum(len(r.get("unverified_numbers", [])) for r in ran),
            "probability_stated": sum(bool(r.get("probability_stated")) for r in ran),
            "other_findings": sum(r.get("other_findings", 0) for r in ran),
            # Share of repeated cases in which every repeat gave the same status.
            "same_status_across_repeats": (sum(len(s) == 1 for s in repeated) / len(repeated)
                                           if repeated else None),
            "no_answer": sum(bool(r.get("no_answer")) for r in ran),
            "partial_runs": sum(bool(r["usage"].get("partial")) for r in ran),
            # Cost covers every row, also the ones that failed, because they were paid for.
            "calls": sum(r["usage"].get("calls", 0) for r in rows),
            "input_tokens": sum(r["usage"].get("input_tokens", 0) for r in rows),
            "output_tokens": sum(r["usage"].get("output_tokens", 0) for r in rows),
            "sessions": sum(r["usage"].get("sessions", 0) for r in rows),
            "acus": sum(r["usage"].get("acus") or 0 for r in rows) or None,
            "seconds": round(sum(r["seconds"] for r in rows), 1)}
