"""Scripted providers for the fictional emissions example (specification section 14)."""
import re

from backend.models import AnswerStatus, EvidenceStatus, Mechanism
from backend.providers.base import (
    ClaimDraft, EvidenceAnalysis, EvidenceJudgment, EvidenceScoreDraft, InputDraft, ProgramDraft,
    ProviderError, QuestionAnswer, Reassessment, Report, ReviewResult, StateUpdate,
)
from backend.models import CalcStep

REPORT = b"""<html><body>
<h1>Example Manufacturing sustainability update</h1>
<p>We reduced our total operational emissions by 40% in 2025 compared with 2024.</p>
<table><caption>Reported operational data</caption>
<tr><th>Quantity</th><th>2024</th><th>2025</th></tr>
<tr><td>Operational emissions per unit (kg CO2e/unit)</td><td>10</td><td>6</td></tr>
<tr><td>Corresponding units produced</td><td>1,000</td><td>2,000</td></tr></table>
<p class="footnote">Methodology note: the same operations, measurement method, and output
definition apply in both periods.</p>
</body></html>"""

ARTICLE = b"<html><body><p>Example Manufacturing says operational emissions per unit fell from " \
          b"10 to 6 kg CO2e between 2024 and 2025.</p></body></html>"

REWRITE = ("According to the reported figures, emissions per unit fell 40%, while total "
           "operational emissions increased 20% as output doubled.")


def _judgment(span_id, quote, relationship, target="claim", denominator=None, repeats=None):
    return EvidenceJudgment(span_id=span_id, quote=quote, relationship=relationship, target=target,
                            differs_on=["denominator"] if denominator else [],
                            origin="company_reported", repeats_span_id=repeats, limitations=[])


class FakeLLM:
    def __init__(self, manifest=None):
        self.analyze_calls = 0

    def extract_claims(self, span, context):
        if "total operational emissions" not in span.text:
            return []
        return [ClaimDraft(quote=span.text, assertion_type="numerical_comparison",
                           subject="Example Manufacturing", assertion="reduced",
                           metric="total operational emissions", value="40", unit="%",
                           denominator=None, population=None, boundary=None,
                           period="2025 compared with 2024", qualifications=[])]

    def plan_questions(self, claim, checklist):
        return []

    def analyze_evidence(self, claim, questions, context):
        self.analyze_calls += 1
        spans = dict(re.findall(r"\[([^\]]+)\] ([^\n]+)", context))
        intensity = next(i for i, t in spans.items() if "per unit" in t and "|" in t)
        units = next(i for i, t in spans.items() if "units produced" in t)
        note = next(i for i, t in spans.items() if "Methodology note" in t)
        judgments = [
            _judgment(intensity, "2024: 10 | 2025: 6", "contradicts", denominator="unit"),
            _judgment(units, "2024: 1,000 | 2025: 2,000", "context"),
            _judgment(note, "the same operations, measurement method", "supports",
                      target=questions[2].id),
        ]
        first = intensity
        for span_id, text in spans.items():
            if text.startswith("Example Manufacturing says"):
                judgments.append(_judgment(span_id, "per unit fell from 10 to 6", "qualifies",
                                           denominator="unit", repeats=first))

        def value(name, number, unit, period, source):
            return InputDraft(name=name, value=number, unit=unit, period=period, population=None,
                              boundary=None, source_span_id=source)

        program = ProgramDraft(note="totals from reported intensity and output",
                               claim_output="total_change", claim_expected="-40", inputs=[
            value("i24", "10", "kg CO2e/unit", "2024", intensity),
            value("i25", "6", "kg CO2e/unit", "2025", intensity),
            value("u24", "1,000", "unit", "2024", units),
            value("u25", "2,000", "unit", "2025", units)], steps=[
            CalcStep(op="reduction", args=["i24", "i25"], out="intensity_reduction"),
            CalcStep(op="multiply", args=["i24", "u24"], out="e24"),
            CalcStep(op="multiply", args=["i25", "u25"], out="e25"),
            CalcStep(op="pct_change", args=["e24", "e25"], out="total_change")])
        answers = [
            QuestionAnswer(question_id=questions[0].id, status=AnswerStatus.answered,
                           answer="The 40% figure is intensity-based.", evidence_span_ids=[intensity]),
            QuestionAnswer(question_id=questions[1].id, status=AnswerStatus.answered,
                           answer="Baseline 2024: 10 kg CO2e per unit.", evidence_span_ids=[intensity]),
            QuestionAnswer(question_id=questions[2].id, status=AnswerStatus.answered,
                           answer="Same operations and method.", evidence_span_ids=[note]),
        ]
        return EvidenceAnalysis(judgments=judgments, programs=[program], answers=answers)

    def update_state(self, state, new_evidence_ids, new_calculation_ids):
        # The verdict depends on the verified calculations in the state it is given.
        tested = [c for c in state.calculations if c.claim_relation == "disagrees"]
        if not tested:
            return StateUpdate(status=EvidenceStatus.insufficient, mechanisms=[], summary="",
                               unresolved=["No calculation tests the claim yet."], explanation="")
        change = tested[0].outputs[tested[0].claim_output]
        return StateUpdate(status=EvidenceStatus.contradicted,
                           mechanisms=[Mechanism.scope, Mechanism.magnitude],
                           summary="The figures support lower emissions per unit, not lower totals.",
                           unresolved=[],
                           explanation=f"Totals computed from the report changed by {change}%.")

    def reassess(self, target, claim, evidence, calculations, questions):
        tested = [c for c in calculations if c.claim_relation == "disagrees"]
        status = EvidenceStatus.contradicted if tested else EvidenceStatus.insufficient
        return Reassessment(status=status, mechanisms=[Mechanism.scope] if tested else [],
                            summary="Assessed from the active evidence only.", unresolved=[],
                            explanation="", probability=0.9 if tested else None)

    def score_evidence(self, target, claim, evidence, calculations):
        # A fixed synthetic value per group, larger when a linked calculation disagrees.
        self.score_calls = getattr(self, "score_calls", 0) + 1
        tested = any(c.claim_relation == "disagrees" for c in calculations)
        return EvidenceScoreDraft(log_evidence=1.5 if tested else 0.25,
                                  supporting_evidence_ids=[e.id for e in evidence],
                                  short_basis="scripted value for tests")

    def review(self, state, decisive):
        return ReviewResult(decision="accept", narrowed_status=None, reasons=[])

    def report(self, state, decisive):
        return Report(summary="The reported figures support lower emissions per unit, not lower "
                              "total emissions.", supported_rewrite=REWRITE,
                      source_independence="company-reported figures only",
                      measurement_limitations=["The inventory was not independently remeasured."],
                      interpretation_ambiguity="low")

    def embed(self, texts):
        raise ProviderError("no embeddings in tests")

    def discover(self, query):
        return []
