import type { ReactNode } from "react";
import type { Claim, Finding, Span } from "@/lib/api";

type Props = {
  spans: Span[];
  claims: Claim[];
  findings: Finding[];
  selected: string | null;
  onSelect: (claimId: string) => void;
};

// Shows the preserved passages in order and marks every claim at its stored offsets.
export function Reader({ spans, claims, findings, selected, onSelect }: Props) {
  return (
    <article className="reader">
      {spans.map((span) => {
        const Tag = span.kind === "heading" ? "h2" : "p";
        const inSpan = claims.filter((c) => c.span_id === span.id).sort((a, b) => a.start - b.start);
        const parts: ReactNode[] = [];
        let cursor = 0;
        for (const claim of inSpan) {
          const from = claim.start - span.start;
          const to = claim.end - span.start;
          if (from < cursor) continue; // overlaps the previous claim
          const finding = findings.find((f) => f.claim_id === claim.id);
          parts.push(span.text.slice(cursor, from));
          parts.push(
            <mark
              key={claim.id}
              role="button"
              tabIndex={0}
              aria-pressed={selected === claim.id}
              title={finding?.summary}
              onClick={() => onSelect(claim.id)}
              onKeyDown={(e) => e.key === "Enter" && onSelect(claim.id)}
            >
              {span.text.slice(from, to)}
              <span className="status">{finding?.evidence_status ?? "pending"}</span>
            </mark>,
          );
          cursor = to;
        }
        parts.push(span.text.slice(cursor));
        return <Tag key={span.id} className={span.kind}>{parts}</Tag>;
      })}
    </article>
  );
}
