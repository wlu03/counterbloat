"""Score one arm's output for one case. Every check is done by code against the case's documents."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from backend.models import SourceSpan
from evaluation.comparison.schema import AuditOutput, Case

TOLERANCE = Decimal("0.05")


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


def score(case: Case, passages: dict[str, list[SourceSpan]], output: AuditOutput) -> dict:
    expected = case.expected
    wanted = _squash(expected.claim_contains)
    finding = next((f for f in output.findings if wanted in _squash(f.claim_quote)
                    or (len(f.claim_quote) > 20 and _squash(f.claim_quote) in wanted)), None)
    result = {"claim_found": finding is not None, "status": finding.status if finding else None,
              "status_correct": bool(finding) and finding.status in expected.accept_statuses,
              "other_findings": len(output.findings) - (1 if finding else 0)}
    if finding is None:
        return result
    texts = {d: [_squash(s.text) for s in spans] for d, spans in passages.items()}
    everything = [t for spans in texts.values() for t in spans]
    # A quote counts when it is an exact substring of a passage of the document it names. When
    # the named document is not one of the supplied ones, every supplied passage is searched.
    exact = [any(_squash(q.quote) in t for t in texts.get(q.document_id, everything))
             for q in finding.evidence if q.quote.strip()]
    stated = _numbers(f"{finding.summary} {finding.supported_rewrite or ''}")
    computed = [v for v in (_decimal(n.value) for n in finding.computed) if v is not None]
    allowed = [n for t in everything for n in _numbers(t)] + [
        v for v in map(_decimal, expected.derived_numbers + expected.key_numbers) if v is not None]
    keys = [k for k in map(_decimal, expected.key_numbers) if k is not None]
    result.update(
        quotes=len(exact), quotes_exact=sum(exact),
        key_numbers=len(keys),
        key_numbers_found=sum(any(_close(k, n) for n in computed + stated) for k in keys),
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
            "calls": sum(r["usage"].get("calls", 0) for r in ran),
            "input_tokens": sum(r["usage"].get("input_tokens", 0) for r in ran),
            "output_tokens": sum(r["usage"].get("output_tokens", 0) for r in ran),
            "acus": sum(r["usage"].get("acus") or 0 for r in ran) or None,
            "seconds": round(sum(r["seconds"] for r in ran), 1)}
