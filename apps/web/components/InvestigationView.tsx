import type { Question } from "@/lib/api";

type Update = { version: number; previous_status: string; new_status: string; explanation: string };

export function InvestigationView({ questions, coverage, updates, stopReason }:
  { questions: Question[]; coverage: number; updates: Update[]; stopReason: string | null }) {
  return (
    <section aria-label="Investigation">
      <h3>Investigation</h3>
      <ul>
        {questions.map((q) => (
          <li key={q.id}>{q.text} <em>({q.status}{q.critical ? ", critical" : ""})</em>
            {q.answer && <><br />{q.answer}</>}</li>
        ))}
      </ul>
      {updates.map((u) => (
        <p key={u.version}>Update {u.version}: {u.previous_status} to {u.new_status}. {u.explanation}</p>
      ))}
      <p>Checklist questions answered, weighted by materiality: {Math.round(coverage * 100)}%.
        This is not a confidence level.</p>
      <p>Stopped because: {stopReason ?? "still running"}.</p>
    </section>
  );
}
