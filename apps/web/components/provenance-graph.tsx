import {
  ChevronRight,
  FileText,
  Quote,
  FlaskConical,
  Gavel,
  ShieldCheck,
  ShieldOff,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { VERDICT_LABELS, type Trace } from "@/lib/types"

const supportText: Record<string, string> = {
  for: "text-supported",
  against: "text-contradicted",
  neutral: "text-muted-foreground",
}

const supportLabel: Record<string, string> = {
  for: "supports",
  against: "contradicts",
  neutral: "qualifies",
}

function ColumnHead({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-3 text-[0.62rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
      {children}
    </div>
  )
}

export function ProvenanceGraph({ trace }: { trace: Trace }) {
  // Unique sources, each carrying independence.
  const sources = Array.from(
    trace.evidence.reduce((m, e) => {
      if (!m.has(e.source)) m.set(e.source, e.independent)
      return m
    }, new Map<string, boolean>()),
  ).map(([name, independent]) => ({ name, independent }))

  const anyIndependent = sources.some((s) => s.independent)

  return (
    <div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        A stable left-to-right map from sources to the final assessment.
        Observations from the same self-reported source share one observation
        base — repetition does not add independent support.
      </p>

      <div className="mt-4 grid gap-x-3 gap-y-4 md:grid-cols-4">
        {/* Sources */}
        <div>
          <ColumnHead>Sources</ColumnHead>
          <ul className="flex flex-col gap-2">
            {sources.map((s) => (
              <li
                key={s.name}
                className="rounded-lg border border-border bg-card p-2.5"
              >
                <div className="flex items-start gap-1.5">
                  <FileText className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  <span className="text-xs font-medium leading-snug text-foreground">
                    {s.name}
                  </span>
                </div>
                <span
                  className={cn(
                    "mt-1.5 inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[0.6rem] font-medium",
                    s.independent
                      ? "bg-supported-bg text-supported"
                      : "bg-unverifiable-bg text-unverifiable",
                  )}
                >
                  {s.independent ? (
                    <ShieldCheck className="size-2.5" />
                  ) : (
                    <ShieldOff className="size-2.5" />
                  )}
                  {s.independent ? "Independent" : "Self-reported"}
                </span>
              </li>
            ))}
          </ul>
        </div>

        {/* Observations */}
        <div>
          <ColumnHead>Observations</ColumnHead>
          <ul className="flex flex-col gap-2">
            {trace.evidence.map((e) => (
              <li key={e.id} className="rounded-lg border border-border bg-card p-2.5">
                <div className="flex items-start gap-1.5">
                  <Quote className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  <span className="font-mono text-[0.68rem] leading-snug text-foreground">
                    {e.excerpt}
                  </span>
                </div>
                <div className="mt-1.5 flex items-center gap-1 text-[0.6rem] text-muted-foreground">
                  <span>derived from {e.source}</span>
                  <ChevronRight className="size-2.5" />
                  <span className={cn("font-medium", supportText[e.supports])}>
                    {supportLabel[e.supports]}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>

        {/* Verification findings */}
        <div>
          <ColumnHead>Verification findings</ColumnHead>
          <ul className="flex flex-col gap-2">
            {trace.checks.map((c) => (
              <li key={c.id} className="rounded-lg border border-border bg-card p-2.5">
                <div className="flex items-start gap-1.5">
                  <FlaskConical className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                  <span className="text-xs font-medium leading-snug text-foreground">
                    {c.name}
                  </span>
                </div>
                <span
                  className={cn(
                    "mt-1.5 inline-block text-[0.6rem] font-medium uppercase tracking-wide",
                    c.status === "pass"
                      ? "text-supported"
                      : c.status === "fail"
                        ? "text-contradicted"
                        : c.status === "warn"
                          ? "text-partial"
                          : "text-muted-foreground",
                  )}
                >
                  {c.status === "pass"
                    ? "confirms"
                    : c.status === "fail"
                      ? "contradicts"
                      : "qualifies"}
                </span>
              </li>
            ))}
            {!anyIndependent && (
              <li className="rounded-lg border border-dashed border-border bg-secondary/40 p-2.5 text-[0.68rem] leading-relaxed text-muted-foreground">
                No independent corroboration admitted — findings rest on a single
                self-reported base.
              </li>
            )}
          </ul>
        </div>

        {/* Assessment */}
        <div>
          <ColumnHead>Claim assessment</ColumnHead>
          <div className="rounded-lg border border-border bg-secondary/40 p-3">
            <div className="flex items-start gap-1.5">
              <Gavel className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
              <span className="text-sm font-semibold text-foreground">
                {VERDICT_LABELS[trace.verdict]}
              </span>
            </div>
            <p className="mt-2 text-[0.68rem] leading-relaxed text-muted-foreground">
              {trace.finding.supportedWording}
            </p>
          </div>
        </div>
      </div>

      {/* Edge legend */}
      <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 text-[0.62rem] text-muted-foreground">
        <span className="font-semibold uppercase tracking-wide">Relationships</span>
        <span className="text-supported">supports / confirms</span>
        <span className="text-contradicted">contradicts</span>
        <span className="text-partial">qualifies</span>
        <span>derived from</span>
      </div>
    </div>
  )
}
