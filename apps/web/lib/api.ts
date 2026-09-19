export type Span = { id: string; kind: string; text: string; start: number };
export type Claim = { id: string; span_id: string; text: string; start: number; end: number };
export type Question = { id: string; text: string; status: string; answer: string | null; critical: boolean };
export type Evidence = {
  id: string; document_id: string; quote: string; relationship: string; origin: string;
  comparable: boolean; differences: string[]; limitations: string[];
  group_id: string | null; round: number; published_at: string | null;
  target: string; // "claim" or a question id
};
export type Group = { id: string; member_ids: string[]; version: number; active: boolean; history: string[] };
export type Calculation = {
  id: string; note: string; outputs: Record<string, string>; units: Record<string, string>;
  steps: { op: string; args: string[]; out: string }[];
  round: number; lineage: string[]; // lineage holds the ids of the groups the inputs came from
  claim_output: string | null; claim_expected: string | null;
  claim_relation: "agrees" | "disagrees" | "none";
};
export type Finding = {
  claim_id: string; evidence_status: string; mechanisms: string[];
  summary: string; supported_rewrite: string | null; review_status: string;
  uncertainty: {
    critical_missing_questions: string[]; source_independence: string;
    measurement_limitations: string[];
  };
};
export type ClaimDetail = {
  claim: Claim; questions: Question[]; evidence: Evidence[]; withdrawn: Evidence[];
  groups: Group[]; calculations: Calculation[]; coverage: number; stop_reason: string | null;
};
export type Update = {
  version: number; previous_status: string; new_status: string; explanation: string;
  strategy: string; changed_evidence_ids: string[]; changed_calculation_ids: string[];
};
export type Score = {
  group_id: string; group_version: number; log_evidence: number; method: string;
  short_basis: string; supporting_evidence_ids: string[];
};
export type Research = {
  notice: string;
  target: {
    id: string; hypothesis: string; label_space: string[]; rubric: string;
    cutoff: string | null; protocol: string;
  } | null;
  belief: {
    target_id: string; method: string; prior: number | null; prior_provenance: string;
    raw_logit: number | null; raw_probability: number | null;
    calibrated_probability: number | null; calibration_status: string; contributions: Score[];
  } | null;
  updates: {
    version: number; strategy: string; input_state_hash: string;
    previous_score: number | null; new_score: number | null; contributions: Score[];
  }[];
};

export async function api<T>(path: string, body?: unknown, headers?: Record<string, string>): Promise<T> {
  const response = await fetch(`/api/backend/${path}`, {
    method: body === undefined ? "GET" : "POST",
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
  return response.json();
}
