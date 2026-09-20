export type Verdict =
  | "supported"
  | "contradicted"
  | "partially_supported"
  | "unverifiable"

export type CheckStatus = "pass" | "fail" | "warn" | "skip"

/** One verification question or calculation of the investigation. */
export interface VerificationCheck {
  id: string
  name: string
  status: CheckStatus
  detail: string
}

export interface EvidenceItem {
  id: string
  source: string
  /** Measured or decided by someone other than the claimant. */
  independent: boolean
  excerpt: string
  supports: "for" | "against" | "neutral"
}

/** One finding of the backend, in the shape the pages render. */
export interface Trace {
  id: string
  analysisId: string
  claimId: string
  claim: string
  documentTitle: string
  source: string
  verdict: Verdict
  /** Share of checklist questions answered, 0 to 100. It is not a confidence level. */
  coverage: number
  tags: string[]
  createdAt: string
  model: string
  durationMs: number
  tokens: number
  reviewState: string
  finding: {
    summary: string
    supportedWording: string
    sourceIndependence: string
    unresolvedQuestions: string[]
    limitations: string[]
  }
  checks: VerificationCheck[]
  evidence: EvidenceItem[]
  /** Provider calls the backend recorded for the whole analysis, in order. */
  calls: { provider: string; purpose: string; model: string | null; latencyMs: number; tokens: number; error: string | null }[]
}

export const VERDICT_LABELS: Record<Verdict, string> = {
  supported: "Supported",
  contradicted: "Contradicted",
  partially_supported: "Mixed evidence",
  unverifiable: "Insufficient evidence",
}

export const CHECK_LABELS: Record<CheckStatus, string> = {
  pass: "Answered",
  fail: "Contradicts the claim",
  warn: "Qualifies the claim",
  skip: "Open",
}
