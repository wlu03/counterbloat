import type { Finding } from "@/lib/api";

export function FindingPanel({ finding }: { finding: Finding }) {
  const u = finding.uncertainty;
  return (
    <section aria-label="Finding">
      <h3>Finding</h3>
      <p><span className="status-label">Assessment: {finding.evidence_status}</span>
        {finding.mechanisms.length > 0 && ` (${finding.mechanisms.join(", ")})`}</p>
      <p>{finding.summary}</p>
      <p><strong>Supported wording:</strong> {finding.supported_rewrite ?? "None proposed."}</p>
      <p><strong>Source independence:</strong> {u.source_independence || "Not stated."}</p>
      {u.critical_missing_questions.length > 0 && (
        <>
          <strong>Unresolved critical questions</strong>
          <ul>{u.critical_missing_questions.map((q) => <li key={q}>{q}</li>)}</ul>
        </>
      )}
      {u.measurement_limitations.length > 0 && (
        <>
          <strong>Limitations</strong>
          <ul>{u.measurement_limitations.map((l) => <li key={l}>{l}</li>)}</ul>
        </>
      )}
      <p>Review state: {finding.review_status}. Probability: not shown, because none has been
        calibrated for this target.</p>
    </section>
  );
}
