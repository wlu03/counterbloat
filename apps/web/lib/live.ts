/** Server-side access to the Countercheck backend. The API key never reaches the browser. */
import type { ResearchScore } from "./assessment"
import type { CheckStatus, Trace, Verdict } from "./types"

const BASE = process.env.COUNTERCHECK_API_URL ?? "http://127.0.0.1:8000"

type Question = { id: string; text: string; status: string; answer: string | null }
type Evidence = {
  id: string; quote: string; relationship: string; origin: string; target: string
  source_url: string | null
}
type Calculation = {
  id: string; note: string; outputs: Record<string, string>; units: Record<string, string>
  claim_output: string | null; claim_relation: "agrees" | "disagrees" | "none"
}
type BackendTrace = {
  id: string; analysis_id: string; claim_id: string; claim: string; status: string
  mechanisms: string[]; review_status: string; created_at: string | null
  document: { id: string; url: string | null; title: string }
  summary: string; supported_rewrite: string | null
  uncertainty: {
    critical_missing_questions: string[]; source_independence: string
    measurement_limitations: string[]
  }
  coverage: number; questions: Question[]; evidence: Evidence[]; calculations: Calculation[]
  usage: {
    models: Record<string, string>; tokens: number; latency_ms: number
    calls: { provider: string; purpose: string; model: string | null; latency_ms: number | null
             input_tokens: number; output_tokens: number; error: string | null }[]
  }
}
type BackendResearch = {
  target: { id: string; hypothesis: string } | null
  belief: {
    method: string; prior: number | null; prior_provenance: string; calibration_status: string
    contributions: { group_id: string; log_evidence: number; short_basis: string; supporting_evidence_ids: string[] }[]
  } | null
}

async function backend<T>(path: string): Promise<T | null> {
  const response = await fetch(`${BASE}/${path}`, {
    headers: { "X-API-Key": process.env.COUNTERCHECK_API_KEY ?? "" },
    cache: "no-store",
  })
  if (response.status === 404) return null
  if (!response.ok) throw new Error(`backend answered ${response.status} for ${path}`)
  return response.json()
}

const VERDICTS: Record<string, Verdict> = {
  supported: "supported", contradicted: "contradicted", mixed: "partially_supported",
  insufficient: "unverifiable", not_yet_resolvable: "unverifiable",
}
const INDEPENDENT = new Set(["independently_measured", "regulatory_finding"])
const RELATION = {
  agrees: "It agrees with the value the claim states.",
  disagrees: "It disagrees with the value the claim states.",
  none: "It answers a side question and does not test the claim.",
}

function adapt(t: BackendTrace): Trace {
  const questions = t.questions.map((q) => {
    const cited = t.evidence.filter((e) => e.target === q.id).map((e) => e.relationship)
    const status: CheckStatus = q.status !== "answered" ? "skip"
      : cited.includes("contradicts") ? "fail" : cited.includes("qualifies") ? "warn" : "pass"
    return { id: q.id, name: q.text, status,
             detail: q.answer ?? "No passage in the allowed sources answered this question." }
  })
  const calculations = t.calculations.map((c) => {
    const status: CheckStatus = c.claim_relation === "agrees" ? "pass"
      : c.claim_relation === "disagrees" ? "fail" : "warn"
    const results = Object.entries(c.outputs).map(([name, value]) => `${name} = ${Number(value)} ${c.units[name] ?? ""}`.trim())
    return { id: c.id, name: `Calculation: ${c.note || c.id}`, status,
             detail: `${results.join("; ")}. ${RELATION[c.claim_relation]}` }
  })
  return {
    id: t.id, analysisId: t.analysis_id, claimId: t.claim_id, claim: t.claim,
    documentTitle: t.document.title, source: t.document.url ?? "Pasted text",
    verdict: VERDICTS[t.status] ?? "unverifiable", coverage: Math.round(t.coverage * 100),
    tags: t.mechanisms, createdAt: t.created_at ?? "",
    model: t.usage.models.reason ?? "not recorded", durationMs: t.usage.latency_ms,
    tokens: t.usage.tokens, reviewState: t.review_status.replace(/_/g, " "),
    finding: {
      summary: t.summary, supportedWording: t.supported_rewrite ?? "",
      sourceIndependence: t.uncertainty.source_independence,
      unresolvedQuestions: t.uncertainty.critical_missing_questions,
      limitations: t.uncertainty.measurement_limitations,
    },
    checks: [...calculations, ...questions],
    calls: t.usage.calls.map((c) => ({
      provider: c.provider, purpose: c.purpose, model: c.model, latencyMs: c.latency_ms ?? 0,
      tokens: c.input_tokens + c.output_tokens, error: c.error,
    })),
    evidence: t.evidence.map((e) => ({
      id: e.id, source: e.source_url ?? t.document.title, independent: INDEPENDENT.has(e.origin),
      excerpt: e.quote,
      supports: e.relationship === "supports" ? "for" : e.relationship === "contradicts" ? "against" : "neutral",
    })),
  }
}

/** Every finding, newest first. `error` is set when the backend cannot be reached. */
export async function getTraces(): Promise<{ traces: Trace[]; error: string | null }> {
  try {
    const records = (await backend<BackendTrace[]>("traces")) ?? []
    const traces = records.map(adapt).sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    return { traces, error: null }
  } catch (problem) {
    return { traces: [], error: String(problem) }
  }
}

/** One finding, with its internal research score when the backend serves one. */
export async function getTrace(id: string): Promise<{ trace: Trace; score: ResearchScore | null } | null> {
  const record = await backend<BackendTrace>(`traces/${encodeURIComponent(id)}`)
  if (!record) return null
  // The research view answers 404 unless the server has it enabled.
  const research = await backend<BackendResearch>(`claims/${encodeURIComponent(record.claim_id)}/research`)
  const belief = research?.belief
  const quotes = new Map(record.evidence.map((e) => [e.id, e.quote]))
  const score: ResearchScore | null =
    belief && belief.method === "evidence_accumulator" && belief.prior !== null && research?.target
      ? {
          targetId: research.target.id, hypothesis: research.target.hypothesis,
          prior: belief.prior, priorProvenance: belief.prior_provenance,
          calibration: belief.calibration_status,
          contributions: belief.contributions.map((c) => ({
            id: c.group_id, logEvidence: c.log_evidence, detail: c.short_basis,
            label: quotes.get(c.supporting_evidence_ids[0] ?? "") ?? c.group_id,
          })),
        }
      : null
  return { trace: adapt(record), score }
}

export interface Aggregates {
  total: number
  averageCoverage: number
  contradictionRate: number
  independentShare: number
  verdictCounts: Record<Verdict, number>
  tagCounts: { tag: string; count: number }[]
  daily: { date: string; count: number }[]
}

export function getAggregates(list: Trace[]): Aggregates {
  const verdictCounts: Record<Verdict, number> = {
    supported: 0, contradicted: 0, partially_supported: 0, unverifiable: 0,
  }
  const tags = new Map<string, number>()
  const days = new Map<string, number>()
  const evidence = list.flatMap((t) => t.evidence)
  for (const t of list) {
    verdictCounts[t.verdict]++
    for (const tag of t.tags) tags.set(tag, (tags.get(tag) ?? 0) + 1)
    if (t.createdAt) days.set(t.createdAt.slice(0, 10), (days.get(t.createdAt.slice(0, 10)) ?? 0) + 1)
  }
  const total = list.length || 1
  return {
    total: list.length,
    averageCoverage: Math.round(list.reduce((sum, t) => sum + t.coverage, 0) / total),
    contradictionRate: Math.round((verdictCounts.contradicted / total) * 100),
    independentShare: evidence.length
      ? Math.round((evidence.filter((e) => e.independent).length / evidence.length) * 100) : 0,
    verdictCounts,
    tagCounts: [...tags].map(([tag, count]) => ({ tag, count })).sort((a, b) => b.count - a.count),
    daily: [...days].map(([date, count]) => ({ date, count })).sort((a, b) => a.date.localeCompare(b.date)),
  }
}
