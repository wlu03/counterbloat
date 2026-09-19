import type { Research } from "@/lib/api";

// Scores are shown as plain numbers with 3 decimals, never as percentages.
const fixed = (n: number | null) => (n === null ? "none" : n.toFixed(3));
const signed = (n: number) => (n < 0 ? "" : "+") + n.toFixed(3);

export function ResearchPanel({ research }: { research: Research }) {
  const { notice, target, belief, updates } = research;
  return (
    <section className="research" aria-label="Internal research scores">
      <h3>Internal research scores (experimental)</h3>
      <p>{notice}</p>
      {target && (
        <p><strong>Target hypothesis:</strong> {target.hypothesis}<br />
          <strong>Protocol:</strong> {target.protocol}</p>
      )}
      {belief ? (
        <>
          <p>Calibration status: {belief.calibration_status}.{" "}
            {belief.calibrated_probability === null
              ? "No calibrated probability exists for this target."
              : `Calibrated probability for this target: ${fixed(belief.calibrated_probability)}.`}</p>
          <p>Prior: {fixed(belief.prior)}{belief.prior_provenance && ` (${belief.prior_provenance})`}.</p>
          <p>Raw uncalibrated score for this target: {fixed(belief.raw_probability)} (log-odds{" "}
            {fixed(belief.raw_logit)}). Method: {belief.method}.</p>
          {belief.contributions.length > 0 && (
            <table>
              <caption>Contribution of each scoring unit to the raw score</caption>
              <thead>
                <tr><th>Unit (source groups)</th><th>Log evidence</th><th>Method</th><th>Basis</th></tr>
              </thead>
              <tbody>
                {belief.contributions.map((s) => (
                  <tr key={s.group_id}>
                    <td>{s.group_id}</td><td>{signed(s.log_evidence)}</td>
                    <td>{s.method}</td><td>{s.short_basis}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      ) : <p>The configured updating strategy does not produce a score.</p>}
      {updates.map((u) => (
        <p key={u.version}>Update {u.version} ({u.strategy}): raw score {fixed(u.previous_score)} →{" "}
          {fixed(u.new_score)}.</p>
      ))}
    </section>
  );
}
