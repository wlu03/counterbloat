// Real earnings calls from the backend, and the ledger a run of one produces.
import { api } from "@/lib/api";

export type CallRecord = {
  id: string;
  ticker: string;
  company: string;
  period: string;
  callDate: string;
  cik: string;
  accession: string;
  sourceUrl: string;
  summary: string;
  audioVintage?: string;
};

export type LedgerEvidence = {
  agent: string;
  tier: "structured" | "filing_text" | "peer_comparison" | "external";
  stance: "supports" | "neutral" | "contradicts" | "context" | "not_found";
  span: string | null;
  accession: string | null;
  matchScore: number;
};

export type LedgerClaim = {
  id: string;
  text: string;
  speaker: string;
  segment: "prepared" | "qa" | "unknown";
  claimType: string;
  topic: string;
  specificity: number;
  hedgingDelta: number;
  rhetoricalInflation: number;
  /** Null when no agent took a side, which is not the same as nothing being wrong. */
  evidenceGap: number | null;
  /** Accumulated from the evidence under a neutral prior. Never fitted to an outcome. */
  probability: number | null;
  probabilityBasis: { group: string; log_evidence: number; basis: string }[];
  verdict: "overstated" | "supported" | "mixed" | "abstain";
  evidence: LedgerEvidence[];
};

export type Ledger = {
  transcriptId: string;
  status?: "running" | "done" | "failed";
  error?: string;
  claims: LedgerClaim[];
  extractedSentences: number;
  claimsFound: number;
  evidenceItems: number;
  abstainRate: number;
  /** False while no curve is fitted. The note says why. */
  calibrated: boolean;
  calibrationNote?: string;
};

export async function listCalls(): Promise<CallRecord[]> {
  const { calls } = await api<{ calls: CallRecord[] }>("calls");
  return calls;
}

export async function startRun(callId: string): Promise<Ledger> {
  return api<Ledger>(`calls/${callId}/run`, {});
}

export async function readLedger(callId: string): Promise<Ledger | null> {
  try {
    return await api<Ledger>(`calls/${callId}/ledger`);
  } catch {
    return null; // Nothing has been run for this call yet.
  }
}

/** Poll until the run finishes. A run reads the call, the filing, and the filed figures. */
export async function waitForLedger(callId: string, everyMs = 2500,
                                    attempts = 120): Promise<Ledger> {
  for (let i = 0; i < attempts; i += 1) {
    const ledger = await readLedger(callId);
    if (ledger && ledger.status !== "running") return ledger;
    await new Promise((resolve) => setTimeout(resolve, everyMs));
  }
  throw new Error("the run did not finish in time");
}
