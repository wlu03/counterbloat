import type { CheckStatus } from "./types"

/**
 * The internal research score of one finding, as the backend's evidence accumulator recorded it:
 *
 *   raw score = sigmoid( logit(prior) + sum of the log-evidence of each source unit )
 *
 * The values are estimates by a language model for one declared target. They are not calibrated,
 * they are not a probability that the claim is false, and the finding does not use them. The
 * backend serves them only when its research view is enabled.
 */
export interface Contribution {
  id: string
  /** A quote from the source unit, or its id. */
  label: string
  /** The scorer's one-sentence basis. */
  detail: string
  logEvidence: number
}

export interface ResearchScore {
  targetId: string
  hypothesis: string
  prior: number
  priorProvenance: string
  calibration: string
  contributions: Contribution[]
}

const logit = (p: number) => Math.log(p / (1 - p))
const sigmoid = (x: number) => 1 / (1 + Math.exp(-x))

export interface AssessmentUpdate {
  index: number
  kind: "prior" | "check"
  checkId?: string
  status?: CheckStatus
  label: string
  detail: string
  /** raw score before this update (0..1) */
  prev: number
  /** raw score after this update (0..1) */
  value: number
  /** signed change of the raw score */
  delta: number
}

/** The score after each source unit is added, in the recorded order. Excluding a unit recomputes
 *  the same sum without it, which is arithmetic on recorded values and changes nothing stored. */
export function buildAssessmentHistory(
  score: ResearchScore,
  excluded: ReadonlySet<string> = new Set(),
): AssessmentUpdate[] {
  const updates: AssessmentUpdate[] = [{
    index: 0, kind: "prior", label: "Declared prior", detail: score.priorProvenance,
    prev: score.prior, value: score.prior, delta: 0,
  }]
  let logOdds = logit(score.prior)
  let index = 1
  for (const c of score.contributions) {
    if (excluded.has(c.id)) continue
    const prev = sigmoid(logOdds)
    logOdds += c.logEvidence
    const value = sigmoid(logOdds)
    updates.push({
      index, kind: "check", checkId: c.id, label: c.label, detail: c.detail, prev, value,
      delta: value - prev,
      // Positive log-evidence favours the overstatement hypothesis, which counts against the claim.
      status: c.logEvidence > 0 ? "fail" : c.logEvidence < 0 ? "pass" : "warn",
    })
    index += 1
  }
  return updates
}

export function finalEstimate(updates: AssessmentUpdate[]): number {
  return updates[updates.length - 1].value
}

/** A raw score is shown as a plain number, never as a percentage. */
export const toScore = (p: number) => p.toFixed(3)
