import type { Claim, Finding, Span } from "@/lib/api";

type Props = {
  spans: Span[];
  claims: Claim[];
  findings: Finding[];
  selected: string | null;
  onSelect: (claimId: string) => void;
};

// Shows the preserved passages in order and marks each claim at its stored offsets.
export function Reader({ spans, claims, findings, selected, onSelect }: Props) {
  return (
    <article className="reader">
      {spans.map((span) => {
        const Tag = span.kind === "heading" ? "h2" : "p";
        const claim = claims.find((c) => c.span_id === span.id);
        if (!claim) return <Tag key={span.id} className={span.kind}>{span.text}</Tag>;
        const finding = findings.find((f) => f.claim_id === claim.id);
        const from = claim.start - span.start;
        const to = claim.end - span.start;
        return (
          <Tag key={span.id} className={span.kind}>
            {span.text.slice(0, from)}
            <mark
              role="button"
              tabIndex={0}
              aria-pressed={selected === claim.id}
              title={finding?.summary}
              onClick={() => onSelect(claim.id)}
              onKeyDown={(e) => e.key === "Enter" && onSelect(claim.id)}
            >
              {span.text.slice(from, to)}
              <span className="status">{finding?.evidence_status ?? "pending"}</span>
            </mark>
            {span.text.slice(to)}
          </Tag>
        );
      })}
    </article>
  );
}
