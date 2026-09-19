"""Data contracts shared by every backend module (specification section 13.1)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, Field


class Mode(StrEnum):
    live = "live"
    frozen = "frozen"
    replay = "replay"


class AssertionType(StrEnum):
    reported_achievement = "reported_achievement"
    numerical_comparison = "numerical_comparison"
    capability = "capability"
    causal_benefit = "causal_benefit"
    product_attribute = "product_attribute"
    policy_commitment = "policy_commitment"
    future_target = "future_target"
    promotional = "promotional"


class EvidenceStatus(StrEnum):
    supported = "supported"
    contradicted = "contradicted"
    mixed = "mixed"
    insufficient = "insufficient"
    not_yet_resolvable = "not_yet_resolvable"


class Mechanism(StrEnum):
    magnitude = "magnitude"
    scope = "scope"
    selective_comparison = "selective_comparison"
    omitted_qualification = "omitted_qualification"
    causal_overreach = "causal_overreach"


class EvidenceOrigin(StrEnum):
    company_reported = "company_reported"
    independently_measured = "independently_measured"
    third_party_repetition = "third_party_repetition"
    regulatory_finding = "regulatory_finding"
    other = "other"


class Relationship(StrEnum):
    supports = "supports"
    contradicts = "contradicts"
    qualifies = "qualifies"
    context = "context"


class ReviewState(StrEnum):
    draft = "draft"
    checks_passed = "checks_passed"
    human_reviewed = "human_reviewed"
    blocked = "blocked"


class AnswerStatus(StrEnum):
    open = "open"
    answered = "answered"
    unanswerable = "unanswerable"


class DocumentSnapshot(BaseModel):
    id: str
    url: str | None = None
    sha256: str
    media_type: str
    published_at: datetime | None = None
    retrieved_at: datetime
    # Earliest time the content is known to have been available. None means unknown.
    admissible_from: datetime | None = None
    parser_version: str
    quality_flags: list[str] = []


class TableCell(BaseModel):
    header: str
    text: str


class TableRow(BaseModel):
    caption: str | None = None
    row_label: str
    cells: list[TableCell]


class SourceSpan(BaseModel):
    id: str
    document_id: str
    kind: str  # paragraph | heading | caption | table_row | footnote
    text: str
    start: int  # offsets into the document's normalized text
    end: int
    page: int | None = None
    prev_id: str | None = None
    next_id: str | None = None
    note_ids: list[str] = []
    table: TableRow | None = None


class Claim(BaseModel):
    id: str
    document_id: str
    span_id: str
    version: int = 1
    text: str  # literal wording, an exact substring of the span
    start: int
    end: int
    assertion_type: AssertionType
    subject: str | None = None
    assertion: str | None = None
    metric: str | None = None
    value: str | None = None
    unit: str | None = None
    denominator: str | None = None
    population: str | None = None
    boundary: str | None = None
    period: str | None = None
    qualifications: list[str] = []
    rubric: str = "material-overstatement-v1"


class VerificationQuestion(BaseModel):
    id: str
    claim_id: str
    text: str
    why_it_matters: str = ""
    evidence_needed: str = ""
    # Ordinal rubric values from 1 (low) to 3 (high).
    materiality: int = 2
    answerability: int = 2
    cost: int = 1
    critical: bool = False
    status: AnswerStatus = AnswerStatus.open
    answer: str | None = None
    evidence_ids: list[str] = []


class EvidenceItem(BaseModel):
    id: str
    claim_id: str
    span_id: str
    document_id: str
    quote: str
    relationship: Relationship
    target: str  # "claim" or a question id
    comparable: bool = True
    differences: list[str] = []
    origin: EvidenceOrigin = EvidenceOrigin.company_reported
    group_id: str | None = None
    limitations: list[str] = []


class EvidenceGroup(BaseModel):
    id: str
    member_ids: list[str]
    version: int = 1
    active: bool = True


class CalcInput(BaseModel):
    name: str
    value: Decimal
    unit: str
    period: str | None = None
    population: str | None = None
    boundary: str | None = None
    source_span_id: str


class CalcStep(BaseModel):
    op: str = Field(description="add, subtract, multiply, divide, pct_change, reduction, compare, or sum")
    args: list[str] = Field(description="Names of inputs or of earlier steps' out. Never numbers.")
    out: str = Field(description="Short name for this step's result, such as e24")


class Calculation(BaseModel):
    id: str
    claim_id: str
    inputs: list[CalcInput]
    steps: list[CalcStep]
    outputs: dict[str, Decimal]
    units: dict[str, str]
    # Provenance groups of the inputs. A calculation is not an independent observation.
    lineage: list[str] = []
    note: str = ""
    # The output that measures the quantity the claim states, and how it compares with the
    # claim's stated value. "none" means the calculation only answers a side question.
    claim_output: str | None = None
    claim_expected: Decimal | None = None
    claim_relation: str = "none"  # agrees | disagrees | none


class Assessment(BaseModel):
    status: EvidenceStatus = EvidenceStatus.insufficient
    mechanisms: list[Mechanism] = []
    summary: str = ""


class InvestigationState(BaseModel):
    claim: Claim
    questions: list[VerificationQuestion] = []
    evidence: list[EvidenceItem] = []
    groups: list[EvidenceGroup] = []
    calculations: list[Calculation] = []
    assessment: Assessment = Field(default_factory=Assessment)
    unresolved: list[str] = []
    version: int = 0
    round: int = 0
    stop_reason: str | None = None


class BeliefUpdate(BaseModel):
    id: str
    claim_id: str
    version: int
    previous_status: EvidenceStatus
    new_status: EvidenceStatus
    changed_evidence_ids: list[str]
    changed_calculation_ids: list[str] = []
    explanation: str
    # Always None. No code sets these fields.
    previous_score: float | None = None
    new_score: float | None = None
    model_version: str = ""


class Uncertainty(BaseModel):
    critical_missing_questions: list[str] = []
    source_independence: str = ""
    measurement_limitations: list[str] = []
    interpretation_ambiguity: str = ""


class Finding(BaseModel):
    finding_id: str
    claim_id: str
    claim_version: int
    target_rubric: str
    evidence_status: EvidenceStatus
    mechanisms: list[Mechanism] = []
    summary: str
    evidence_ids: list[str] = []
    calculation_ids: list[str] = []
    supported_rewrite: str | None = None
    uncertainty: Uncertainty = Field(default_factory=Uncertainty)
    probability: float | None = None
    probability_status: str = "not_calibrated_for_this_target"
    review_status: ReviewState = ReviewState.draft
    evidence_cutoff: datetime | None = None
    stop_reason: str | None = None
    is_synthetic_example: bool = False


class ProviderCall(BaseModel):
    provider: str
    purpose: str
    model: str | None = None
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    billing_unit: str = "tokens"
    error: str | None = None


class RunManifest(BaseModel):
    analysis_id: str
    mode: Mode
    config_hash: str
    models: dict[str, str] = {}
    cutoff: datetime | None = None
    calls: list[ProviderCall] = []
    # Operational failures: a provider call, a fetch, or the job itself.
    errors: list[str] = []
    # Model output that failed validation and was discarded. The job still ran in full.
    rejections: list[str] = []
