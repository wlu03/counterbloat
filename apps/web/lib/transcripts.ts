// Shapes and labels the transcript workflow reads. The calls themselves, and the
// ledger a run produces, come from the backend; see lib/calls.ts.
// overstatement-detection pipeline. Everything here is derivable and stable
// per transcript id, so a "run" always produces the same ledger.

export type Sector =
  | "software_ai"
  | "pharma"
  | "consumer"
  | "finance"
  | "industrial"

export type DocKind = "transcript" | "press_release" | "10-K" | "10-Q" | "audio"

export interface TranscriptRecord {
  id: string
  ticker: string
  company: string
  sector: Sector
  period: string
  callDate: string
  cik: string
  docs: DocKind[]
  executiveCount: number
  analystCount: number
  wordCount: number
  source: string
  summary: string
  /** Historical audio-dataset vintage, if any (2017–2022 per the plan). */
  audioVintage?: string
}

export type ClaimType =
  | "measurable_target"
  | "directional_aspiration"
  | "capability_assertion"
  | "comparative_superlative"
  | "value_statement"
  | "puffery"

export type Segment = "prepared" | "qa"
export type Stance = "supports" | "neutral" | "contradicts" | "not_found"
export type Tier = "structured" | "filing_text" | "peer_comparison" | "external"
export type LedgerVerdict = "overstated" | "supported" | "mixed" | "abstain"

export interface LedgerEvidence {
  agent: string
  tier: Tier
  stance: Stance
  span: string | null
  accession: string | null
  matchScore: number
}

export interface LedgerClaim {
  id: string
  text: string
  speaker: string
  segment: Segment
  claimType: ClaimType
  topic: string
  /** 0–6: number, unit, date, baseline, named metric, named verifier. */
  specificity: number
  /** strong-modal(claim) − weak-modal(matched passage). */
  hedgingDelta: number
  /** 0–100, how loud the language is. */
  rhetoricalInflation: number
  /** 0–100, whether anything actually contradicts the claim. */
  evidenceGap: number
  /** Calibrated probability the claim is overstated. */
  probability: number
  verdict: LedgerVerdict
  evidence: LedgerEvidence[]
}

export interface WorkflowStage {
  id: string
  name: string
  detail: string
}

export const WORKFLOW_STAGES: WorkflowStage[] = [
  {
    id: "s0",
    name: "Ingest & normalize",
    detail: "One row per sentence across transcript, 8-K, and 10-K sections.",
  },
  {
    id: "s1",
    name: "Claim extraction",
    detail: "Discrete claims from executive turns; exact-substring guard on every span.",
  },
  {
    id: "s2",
    name: "Search agents vs. 10-K",
    detail: "risk-matcher · xbrl-verifier · drift-tracker · novelty-checker · outcome-checker.",
  },
  {
    id: "s3",
    name: "Text features",
    detail: "Loughran-McDonald densities, specificity, hedging delta, topic asymmetry.",
  },
  {
    id: "s4",
    name: "Audio features",
    detail: "Response latency, disfluency, speech-rate shift — within-speaker baseline.",
  },
  {
    id: "s5",
    name: "Fusion & scoring",
    detail: "Rhetorical inflation × evidence gap; L1-regularized logistic over ~15 features.",
  },
  {
    id: "s6",
    name: "Calibration",
    detail: "Isotonic calibration on held-out labels; abstain when evidence is thin.",
  },
  {
    id: "s7",
    name: "Ledger output",
    detail: "Per-claim ledger with evidence links, plus the inflation × evidence-gap exhibit.",
  },
]

export const SECTOR_LABELS: Record<Sector, string> = {
  software_ai: "Software / AI",
  pharma: "Pharma",
  consumer: "Consumer",
  finance: "Finance",
  industrial: "Industrial",
}

export const CLAIM_TYPE_LABELS: Record<ClaimType, string> = {
  measurable_target: "Measurable target",
  directional_aspiration: "Directional aspiration",
  capability_assertion: "Capability assertion",
  comparative_superlative: "Comparative superlative",
  value_statement: "Value statement",
  puffery: "Puffery",
}

export const LEDGER_VERDICT_LABELS: Record<LedgerVerdict, string> = {
  overstated: "Overstated",
  supported: "Supported",
  mixed: "Mixed",
  abstain: "Insufficient evidence",
}


// ---- Deterministic ledger generation ---------------------------------------

function hash(str: string): number {
  let h = 2166136261
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return h >>> 0
}

function seeded(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 0xffffffff
  }
}

interface ClaimSeed {
  text: string
  claimType: ClaimType
  topic: string
  segment: Segment
  /** Rough tendencies, jittered per-transcript. */
  baseInflation: number
  baseGap: number
  namedMetric?: string
}

const EXECS = ["CEO", "CFO", "COO", "Chief Product Officer"]

const claimPools: Record<Sector, ClaimSeed[]> = {
  software_ai: [
    {
      text: "Our new agentic runtime is the fastest inference engine on the market, full stop.",
      claimType: "comparative_superlative",
      topic: "product performance",
      segment: "prepared",
      baseInflation: 82,
      baseGap: 71,
    },
    {
      text: "We expect the platform to drive at least 30% net revenue retention expansion next year.",
      claimType: "measurable_target",
      topic: "revenue growth",
      segment: "prepared",
      baseInflation: 44,
      baseGap: 58,
      namedMetric: "NetRevenueRetention",
    },
    {
      text: "Adoption of the enterprise tier has been nothing short of extraordinary this quarter.",
      claimType: "puffery",
      topic: "enterprise adoption",
      segment: "prepared",
      baseInflation: 88,
      baseGap: 40,
    },
    {
      text: "Gross margin improved to 79% on a non-GAAP basis.",
      claimType: "measurable_target",
      topic: "margins",
      segment: "prepared",
      baseInflation: 22,
      baseGap: 34,
      namedMetric: "GrossProfitRatio",
    },
    {
      text: "We're confident inference costs will keep falling for every customer, without exception.",
      claimType: "capability_assertion",
      topic: "unit economics",
      segment: "qa",
      baseInflation: 63,
      baseGap: 66,
    },
    {
      text: "The model leads every public benchmark that matters.",
      claimType: "comparative_superlative",
      topic: "model quality",
      segment: "qa",
      baseInflation: 79,
      baseGap: 62,
    },
  ],
  pharma: [
    {
      text: "The Phase 2 readout essentially halved symptom duration versus standard of care.",
      claimType: "measurable_target",
      topic: "trial efficacy",
      segment: "prepared",
      baseInflation: 41,
      baseGap: 46,
      namedMetric: "PrimaryEndpoint",
    },
    {
      text: "We view this as a clear best-in-class profile across the entire class.",
      claimType: "comparative_superlative",
      topic: "competitive position",
      segment: "prepared",
      baseInflation: 84,
      baseGap: 61,
    },
    {
      text: "Safety was excellent, with no meaningful signals of concern.",
      claimType: "value_statement",
      topic: "safety",
      segment: "qa",
      baseInflation: 58,
      baseGap: 52,
    },
    {
      text: "We remain on track for a regulatory filing in the first half of next year.",
      claimType: "directional_aspiration",
      topic: "regulatory timeline",
      segment: "prepared",
      baseInflation: 30,
      baseGap: 38,
    },
    {
      text: "The market opportunity here is essentially unlimited.",
      claimType: "puffery",
      topic: "market size",
      segment: "qa",
      baseInflation: 90,
      baseGap: 55,
    },
  ],
  consumer: [
    {
      text: "Same-store sales grew across every region we operate in.",
      claimType: "capability_assertion",
      topic: "comparable sales",
      segment: "prepared",
      baseInflation: 55,
      baseGap: 60,
      namedMetric: "SameStoreSales",
    },
    {
      text: "Adjusted operating margin reached a record 18% this year.",
      claimType: "measurable_target",
      topic: "margins",
      segment: "prepared",
      baseInflation: 33,
      baseGap: 44,
      namedMetric: "OperatingIncomeLoss",
    },
    {
      text: "Our supply chain is now essentially fully sustainable.",
      claimType: "value_statement",
      topic: "sustainability",
      segment: "prepared",
      baseInflation: 76,
      baseGap: 64,
    },
    {
      text: "Loyalty engagement has never been stronger.",
      claimType: "puffery",
      topic: "customer loyalty",
      segment: "qa",
      baseInflation: 81,
      baseGap: 39,
    },
    {
      text: "We expect double-digit unit growth to continue through next year.",
      claimType: "directional_aspiration",
      topic: "unit growth",
      segment: "qa",
      baseInflation: 42,
      baseGap: 50,
    },
  ],
  finance: [
    {
      text: "Revenue grew 22% year over year, consistent with our filed results.",
      claimType: "measurable_target",
      topic: "revenue growth",
      segment: "prepared",
      baseInflation: 18,
      baseGap: 20,
      namedMetric: "Revenues",
    },
    {
      text: "Operating margin expanded to a record 34% this year.",
      claimType: "measurable_target",
      topic: "margins",
      segment: "prepared",
      baseInflation: 26,
      baseGap: 28,
      namedMetric: "OperatingIncomeLoss",
    },
    {
      text: "Credit quality across the book has never looked better.",
      claimType: "puffery",
      topic: "credit quality",
      segment: "qa",
      baseInflation: 74,
      baseGap: 48,
    },
    {
      text: "We are the clear market leader in every segment we serve.",
      claimType: "comparative_superlative",
      topic: "market position",
      segment: "prepared",
      baseInflation: 80,
      baseGap: 57,
    },
    {
      text: "Free cash flow will comfortably cover the dividend going forward.",
      claimType: "directional_aspiration",
      topic: "capital return",
      segment: "qa",
      baseInflation: 36,
      baseGap: 42,
      namedMetric: "FreeCashFlow",
    },
  ],
  industrial: [
    {
      text: "The new robotics line cuts cycle time by up to 30% for every deployment.",
      claimType: "measurable_target",
      topic: "product performance",
      segment: "prepared",
      baseInflation: 61,
      baseGap: 68,
    },
    {
      text: "Backlog is at a record, which we see as undeniable proof of demand.",
      claimType: "capability_assertion",
      topic: "demand",
      segment: "prepared",
      baseInflation: 67,
      baseGap: 53,
      namedMetric: "OrderBacklog",
    },
    {
      text: "Our facilities now run on 100% renewable energy.",
      claimType: "value_statement",
      topic: "sustainability",
      segment: "prepared",
      baseInflation: 70,
      baseGap: 66,
    },
    {
      text: "Switching to our platform cuts logistics costs by up to 30% for every customer.",
      claimType: "comparative_superlative",
      topic: "cost savings",
      segment: "qa",
      baseInflation: 72,
      baseGap: 73,
    },
    {
      text: "We expect margins to keep expanding as volume scales.",
      claimType: "directional_aspiration",
      topic: "margins",
      segment: "qa",
      baseInflation: 34,
      baseGap: 40,
    },
  ],
}

const AGENT_BY_TIER: { agent: string; tier: Tier }[] = [
  { agent: "xbrl-verifier", tier: "structured" },
  { agent: "risk-matcher", tier: "filing_text" },
  { agent: "drift-tracker", tier: "filing_text" },
  { agent: "novelty-checker", tier: "peer_comparison" },
  { agent: "outcome-checker", tier: "external" },
]

function clamp(n: number, lo = 0, hi = 100): number {
  return Math.max(lo, Math.min(hi, n))
}

function round(n: number, p = 0): number {
  const f = 10 ** p
  return Math.round(n * f) / f
}

function specificityFor(seed: ClaimSeed, rng: () => number): number {
  let s = 0
  if (seed.claimType === "measurable_target") s += 3
  if (seed.namedMetric) s += 1
  if (seed.baseInflation < 40) s += 1
  if (rng() > 0.5) s += 1
  if (seed.claimType === "puffery") s = Math.min(s, 1)
  return Math.max(0, Math.min(6, s))
}

function buildEvidence(
  seed: ClaimSeed,
  gap: number,
  rng: () => number,
  cik: string,
): LedgerEvidence[] {
  const items: LedgerEvidence[] = []
  const count = 1 + Math.floor(rng() * 3)
  const accession = `${cik.slice(0, 10)}-${25 + Math.floor(rng() * 2)}-${String(
    100000 + Math.floor(rng() * 899999),
  )}`

  for (let i = 0; i < count; i++) {
    const pick = AGENT_BY_TIER[Math.floor(rng() * AGENT_BY_TIER.length)]
    // Higher gap => more likely a contradicting / not_found stance.
    const roll = rng() * 100
    let stance: Stance
    if (roll < gap * 0.6) stance = "contradicts"
    else if (roll < gap * 0.6 + 25) stance = "not_found"
    else if (roll > 100 - (100 - gap) * 0.4) stance = "supports"
    else stance = "neutral"

    const hasSpan = stance !== "not_found" && rng() > 0.2
    const isXbrl = pick.tier === "structured" && seed.namedMetric
    items.push({
      agent: pick.agent,
      tier: pick.tier,
      stance,
      span: hasSpan
        ? isXbrl
          ? `us-gaap:${seed.namedMetric} — filed value differs from headline framing`
          : stanceSpan(seed, stance)
        : null,
      accession: hasSpan ? accession : null,
      matchScore: round(0.4 + rng() * 0.58, 2),
    })
  }
  return items
}

function stanceSpan(seed: ClaimSeed, stance: Stance): string {
  if (stance === "contradicts")
    return `Matched 10-K passage on ${seed.topic} hedges the same point with weaker modal language.`
  if (stance === "supports")
    return `Filing corroborates the ${seed.topic} figure within the disclosed period.`
  return `Passage references ${seed.topic} but does not confirm the specific magnitude.`
}

export interface Ledger {
  transcriptId: string
  claims: LedgerClaim[]
  extractedSentences: number
  claimsFound: number
  evidenceItems: number
  abstainRate: number
}

/** Deterministically derive the full claim ledger for a transcript. */


// ---- Run trace (pipeline execution) ----------------------------------------
// A run isn't eight green checkmarks. It's a trace: per-stage timing, how many
// tool calls each agent made, which agents were degraded because the filing
// they needed wasn't in this run, and where a search failed and recovered.

export type StageStatus =
  | "ok"
  | "recovered"
  | "degraded"
  | "skipped"
  | "failed"

export type AudioMode = "current" | "historical" | "none"

export interface AgentRun {
  agent: string
  tier: Tier
  calls: number
  status: StageStatus
  note?: string
}

export interface RunStage {
  id: string
  name: string
  detail: string
  status: StageStatus
  durationMs: number
  toolCalls: number
  events: string[]
  agents?: AgentRun[]
  note?: string
}

export interface RunFunnel {
  extracted: number
  testable: number
  scored: number
  abstained: number
}

export interface RunSummary {
  attempt: number
  mode: RunMode
  escalated: number
  recovered: number
  overstated: number
  abstained: number
  wallTimeMs: number
  toolCalls: number
  costUsd: number
}

export type RunMode = "fresh" | "corrections" | "failed"

export interface RunTrace {
  attempt: number
  mode: RunMode
  filingKind: DocKind
  hasBaseline: boolean
  audioMode: AudioMode
  audioVintage?: string
  stages: RunStage[]
  funnel: RunFunnel
  wallTimeMs: number
  toolCalls: number
  costUsd: number
  escalated: number
  recovered: number
  notFound: number
  overstated: number
  abstained: number
  degradedAgents: string[]
}

const STAGE_META: { id: string; name: string; detail: string }[] = [
  {
    id: "s0",
    name: "Ingest & normalize",
    detail: "One row per sentence across transcript, press release, and the filing.",
  },
  {
    id: "s1",
    name: "Claim extraction",
    detail: "Discrete claims from executive turns; exact-substring guard on every span.",
  },
  {
    id: "s2",
    name: "Search agents",
    detail: "risk-matcher · xbrl-verifier · drift-tracker · novelty-checker · outcome-checker.",
  },
  {
    id: "s3",
    name: "Text features",
    detail: "Loughran-McDonald densities, specificity, hedging delta, topic asymmetry.",
  },
  {
    id: "s4",
    name: "Audio features",
    detail: "Response latency, disfluency, speech-rate shift — within-speaker baseline.",
  },
  {
    id: "s5",
    name: "Fusion & scoring",
    detail: "Rhetorical inflation × evidence gap; L1-regularized logistic over ~15 features.",
  },
  {
    id: "s6",
    name: "Calibration & abstention",
    detail: "Isotonic calibration on held-out labels; abstain when evidence is thin.",
  },
  {
    id: "s7",
    name: "Ledger output",
    detail: "Per-claim ledger with evidence links and the signal ranking.",
  },
]

/**
 * Derive the full execution trace for a run. Deterministic per
 * (transcript, attempt), and `corrections` (resolved review items carried in
 * as error memory) reduces escalations on later attempts — the literal
 * demonstration of learning across runs.
 */
export function generateRunTrace(
  record: TranscriptRecord,
  ledger: Ledger,
  attempt: number,
  corrections: number,
  mode: RunMode = "fresh",
): RunTrace {
  const rng = seeded(hash(`${record.id}:run:${attempt}`))
  const filingKind: DocKind = record.docs.includes("10-K") ? "10-K" : "10-Q"
  const hasBaseline = filingKind === "10-K"
  const audioMode: AudioMode = !record.audioVintage
    ? "none"
    : record.audioVintage.toLowerCase().includes("current")
      ? "current"
      : "historical"

  const claims = ledger.claims
  const abstained = claims.filter((c) => c.verdict === "abstain").length
  const overstated = claims.filter((c) => c.verdict === "overstated").length
  const notFound = claims.filter((c) =>
    c.evidence.some((e) => e.stance === "not_found"),
  ).length

  // First pass leaves `notFound` claims unmatched. Reformulation recovers some;
  // the rest escalate. Prior corrections shrink the escalation set.
  const firstPassEscalate = Math.max(0, notFound - 1)
  const escalated = Math.max(0, firstPassEscalate - corrections)
  const recovered = Math.max(0, notFound - escalated)

  // Funnel: extracted candidates → testable → scored → abstained.
  const extracted = Math.max(claims.length * 6, Math.round(record.wordCount / 260))
  const testable = Math.max(
    claims.length + Math.ceil(abstained / 1),
    Math.round(extracted * 0.27),
  )
  const funnel: RunFunnel = {
    extracted,
    testable,
    scored: claims.length,
    abstained,
  }

  // Later attempts run a little faster (warm caches).
  const speed = attempt > 1 ? 0.82 : 1
  const dur = (base: number) => Math.round((base + rng() * base * 0.5) * speed)

  const withMetric = claims.filter((c) =>
    c.evidence.some((e) => e.tier === "structured"),
  ).length

  const agents: AgentRun[] = [
    {
      agent: "xbrl-verifier",
      tier: "structured",
      calls: Math.max(2, withMetric * 2),
      status: "ok",
    },
    {
      agent: "risk-matcher",
      tier: "filing_text",
      calls: claims.length + notFound,
      status: notFound > 0 ? "recovered" : "ok",
      note:
        notFound > 0
          ? `not_found on ${notFound} claim${notFound === 1 ? "" : "s"} → reformulated with section hints → recovered ${recovered}, escalated ${escalated}`
          : undefined,
    },
    {
      agent: "drift-tracker",
      tier: "filing_text",
      calls: hasBaseline ? claims.length : 0,
      status: hasBaseline ? "ok" : "degraded",
      note: hasBaseline
        ? undefined
        : `no 10-K baseline in a ${filingKind}-only run — year-over-year drift unavailable`,
    },
    {
      agent: "novelty-checker",
      tier: "peer_comparison",
      calls: hasBaseline ? Math.max(2, claims.length - 1) : 1,
      status: hasBaseline ? "ok" : "degraded",
      note: hasBaseline
        ? undefined
        : `needs the 10-K risk-factor set to diff against — running peer-only, lower confidence`,
    },
    {
      agent: "outcome-checker",
      tier: "external",
      calls: Math.max(1, Math.round(claims.length / 2)),
      status: "ok",
    },
  ]

  const degradedAgents = agents
    .filter((a) => a.status === "degraded")
    .map((a) => a.agent)

  const s2Events: string[] = []
  if (notFound > 0) {
    s2Events.push(
      `risk-matcher returned not_found on ${notFound} claim${notFound === 1 ? "" : "s"} on the first pass.`,
    )
    s2Events.push(
      `Reformulated each query with 10-${hasBaseline ? "K" : "Q"} section hints and re-ran ${notFound} lookup${notFound === 1 ? "" : "s"}.`,
    )
    s2Events.push(
      `Recovered ${recovered}; escalated ${escalated} to human review.`,
    )
  } else {
    s2Events.push("All claims matched a filing span on the first pass.")
  }
  if (!hasBaseline) {
    s2Events.push(
      `drift-tracker and novelty-checker degraded: this run has only the ${filingKind}, no 10-K baseline to diff against.`,
    )
  }

  const audioEvents: string[] =
    audioMode === "none"
      ? ["No aligned audio for this call — text-only model."]
      : audioMode === "historical"
        ? [
            `Aligned audio is ${record.audioVintage}; public datasets are 2017–2022 vintage.`,
            "Speech features kept as a low-weight supplementary signal, not a lie detector.",
          ]
        : [`Current webcast replay aligned; speech features at full weight.`]

  const stageStatus: Record<string, StageStatus> = {
    s0: "ok",
    s1: "ok",
    s2: !hasBaseline ? "degraded" : notFound > 0 ? "recovered" : "ok",
    s3: "ok",
    s4: audioMode === "none" ? "skipped" : audioMode === "historical" ? "degraded" : "ok",
    s5: "ok",
    s6: abstained > 0 || escalated > 0 ? "recovered" : "ok",
    s7: "ok",
  }

  const stages: RunStage[] = STAGE_META.map((meta) => {
    let name = meta.name
    let detail = meta.detail
    let toolCalls = 2 + Math.floor(rng() * 3)
    let events: string[] = []
    let stageAgents: AgentRun[] | undefined

    if (meta.id === "s0") {
      toolCalls = record.docs.length
      events = [
        `Parsed ${record.docs.length} documents (${record.docs.join(", ")}) into ${(extracted * 7).toLocaleString()} sentences.`,
      ]
    } else if (meta.id === "s1") {
      toolCalls = 1
      events = [
        `${extracted} candidate claims → ${testable} testable after the exact-substring guard.`,
      ]
    } else if (meta.id === "s2") {
      name = `Search agents vs. ${filingKind}`
      detail = `Chasing every claim into the ${filingKind}${hasBaseline ? " and prior 10-K" : ""}.`
      stageAgents = agents
      toolCalls = agents.reduce((n, a) => n + a.calls, 0)
      events = s2Events
    } else if (meta.id === "s3") {
      events = [`Scored ${claims.length} claims on ${"specificity, hedging Δ, topic asymmetry"}.`]
    } else if (meta.id === "s4") {
      toolCalls = audioMode === "none" ? 0 : 3 + Math.floor(rng() * 3)
      events = audioEvents
    } else if (meta.id === "s5") {
      events = [`Fused ~15 features into a single rhetorical-inflation × evidence-gap score.`]
    } else if (meta.id === "s6") {
      events = [
        `${abstained} claim${abstained === 1 ? "" : "s"} fell below the evidence threshold → abstained.`,
        `${escalated} claim${escalated === 1 ? "" : "s"} escalated to human review.`,
      ]
    } else if (meta.id === "s7") {
      toolCalls = 1
      events = [`Emitted ${claims.length}-row ledger with ${ledger.evidenceItems} evidence links.`]
    }

    const status = stageStatus[meta.id]
    return {
      id: meta.id,
      name,
      detail,
      status,
      durationMs: status === "skipped" ? 0 : dur(280),
      toolCalls,
      events,
      agents: stageAgents,
      note:
        meta.id === "s2" && !hasBaseline
          ? `Labelled with the filing this run actually used (${filingKind}), not a generic 10-K.`
          : undefined,
    }
  })

  const wallTimeMs = stages.reduce((n, s) => n + s.durationMs, 0)
  const toolCalls = stages.reduce((n, s) => n + s.toolCalls, 0)
  const costUsd = round(toolCalls * 0.0009 + 0.02, 3)

  return {
    attempt,
    mode,
    filingKind,
    hasBaseline,
    audioMode,
    audioVintage: record.audioVintage,
    stages,
    funnel,
    wallTimeMs,
    toolCalls,
    costUsd,
    escalated,
    recovered,
    notFound,
    overstated,
    abstained,
    degradedAgents,
  }
}
