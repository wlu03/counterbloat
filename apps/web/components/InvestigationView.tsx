import type { ClaimDetail, Update } from "@/lib/api";

const RELATION = {
  agrees: "agrees with the value the claim states",
  disagrees: "disagrees with the value the claim states",
  none: "answers a side question and does not test the claim",
};

export function InvestigationView({ detail, updates }: { detail: ClaimDetail; updates: Update[] }) {
  const { questions, evidence, withdrawn, groups, calculations } = detail;
  const questionText = new Map(questions.map((q) => [q.id, q.text]));
  const rounds = [...new Set([...evidence, ...calculations].map((x) => x.round))].sort((a, b) => a - b);
  const unresolved = questions.filter((q) => q.critical && q.status !== "answered");
  // The first item of each group in round order. Later items of the same group repeat that source.
  const first = new Map<string, string>();
  for (const e of [...evidence].sort((a, b) => a.round - b.round)) {
    if (e.group_id && !first.has(e.group_id)) first.set(e.group_id, e.id);
  }

  return (
    <section aria-label="Investigation">
      <h3>Investigation</h3>
      <ul>
        {questions.map((q) => (
          <li key={q.id}>{q.text} <em>({q.status}{q.critical ? ", critical" : ""})</em>
            {q.answer && <><br />{q.answer}</>}</li>
        ))}
      </ul>

      {rounds.map((round) => (
        <div key={round}>
          <h4>Round {round}</h4>
          {evidence.filter((e) => e.round === round).map((e) => {
            const original = e.group_id ? first.get(e.group_id) : undefined;
            const about = e.target === "claim" ? "about the claim." : `for the question: ${questionText.get(e.target) ?? e.target}`;
            return (
              <div key={e.id}>
                <blockquote>{e.quote}</blockquote>
                {original && original !== e.id
                  ? <p>{e.id}: repeats the source of {original} above. It is counted once.</p>
                  : <p>{e.id}: {e.relationship}. Admitted as evidence {about}</p>}
              </div>
            );
          })}
          {calculations.filter((c) => c.round === round).map((c) => (
            <p key={c.id}>{c.id}: calculation. {c.note}<br />
              {c.claim_output && `Result: ${Number(c.outputs[c.claim_output])} ${c.units[c.claim_output] ?? ""}`.trim() + ". "}
              {c.claim_expected !== null && `The claim states ${Number(c.claim_expected)}. `}
              The calculation {RELATION[c.claim_relation]}.</p>
          ))}
        </div>
      ))}

      {updates.length > 0 && <h4>Assessment changes</h4>}
      {updates.map((u) => {
        const ids = [...u.changed_evidence_ids, ...u.changed_calculation_ids];
        return (
          <p key={u.version}>Update {u.version} ({u.strategy}): {u.previous_status} → {u.new_status}.{" "}
            {u.explanation}{ids.length > 0 && ` Responded to: ${ids.join(", ")}.`}</p>
        );
      })}

      {withdrawn.length > 0 && (
        <>
          <h4>Withdrawn or corrected sources</h4>
          {withdrawn.map((e) => (
            <div key={e.id}>
              <blockquote>{e.quote}</blockquote>
              <p>{e.id}: admitted in round {e.round}, then removed from the evidence. It is no longer counted.</p>
              <ul>
                {(groups.find((g) => g.id === e.group_id)?.history ?? []).map((line) => <li key={line}>{line}</li>)}
              </ul>
            </div>
          ))}
        </>
      )}

      {unresolved.length > 0 && (
        <>
          <h4>Unresolved checks</h4>
          <ul>{unresolved.map((q) => <li key={q.id}>{q.text} <em>({q.status})</em></li>)}</ul>
        </>
      )}

      <p>Checklist questions answered, weighted by materiality: {Math.round(detail.coverage * 100)}%.
        This is not a confidence level.</p>
      <p>Stopped because: {detail.stop_reason ?? "still running"}.</p>
    </section>
  );
}
