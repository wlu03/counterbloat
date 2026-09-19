export type Span = { id: string; kind: string; text: string; start: number };
export type Claim = { id: string; span_id: string; text: string; start: number; end: number };
export type Question = { id: string; text: string; status: string; answer: string | null; critical: boolean };
export type Evidence = {
  id: string; quote: string; relationship: string; origin: string; comparable: boolean;
  differences: string[];
};
export type Calculation = {
  id: string; note: string; outputs: Record<string, string>; units: Record<string, string>;
  steps: { op: string; args: string[]; out: string }[];
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
  claim: Claim; questions: Question[]; evidence: Evidence[]; calculations: Calculation[];
  coverage: number; stop_reason: string | null;
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
