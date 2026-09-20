import Link from "next/link"
import {
  ArrowLeft,
  ArrowRight,
  Check,
  X,
  TriangleAlert,
  Minus,
  Download,
  Network,
  Terminal,
  HelpCircle,
  ShieldOff,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { CHECK_LABELS, type CheckStatus, type Trace } from "@/lib/types"
import type { ResearchScore } from "@/lib/assessment"
import { Panel, PanelTitle } from "@/components/panel"
import { VerdictBadge } from "@/components/verdict-badge"
import { ExecutionTrace } from "@/components/execution-trace"
import { AssessmentHistory } from "@/components/assessment-history"
import { ProvenanceGraph } from "@/components/provenance-graph"

const checkStyle: Record<CheckStatus, { icon: typeof Check; color: string }> = {
  pass: { icon: Check, color: "text-supported" },
  fail: { icon: X, color: "text-contradicted" },
  warn: { icon: TriangleAlert, color: "text-partial" },
  skip: { icon: Minus, color: "text-muted-foreground" },
}

function formatDateTime(iso: string) {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

export function TraceDetail({ trace, score }: { trace: Trace; score: ResearchScore | null }) {
  const f = trace.finding

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <Link
        href="/traces"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ArrowLeft className="size-4" />
        All traces
      </Link>

      {/* Header: claim + conclusion */}
      <header className="mt-4 flex flex-col gap-4 border-b border-border pb-6">
        <div className="flex flex-wrap items-center gap-2.5">
          <VerdictBadge verdict={trace.verdict} size="md" />
          <span className="font-mono text-xs text-muted-foreground">{trace.id}</span>
          {trace.tags.map((tag) => (
            <span
              key={tag}
              className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[0.68rem] text-muted-foreground"
            >
              {tag}
            </span>
          ))}
        </div>
        <h1 className="font-serif text-3xl leading-tight tracking-tight text-foreground text-balance">
          {trace.claim}
        </h1>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted-foreground">
          <span>{trace.documentTitle}</span>
          <span aria-hidden="true">&middot;</span>
          <span>{trace.source}</span>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          <span>Analysis time: {formatDateTime(trace.createdAt)}</span>
          <span aria-hidden="true">&middot;</span>
          <span>Checklist coverage: {trace.coverage}% (not a confidence level)</span>
        </div>
      </header>

      {/* Original vs supported wording */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2">
        <Panel>
          <PanelTitle>Original wording</PanelTitle>
          <p className="mt-2 font-serif text-lg leading-snug text-foreground text-pretty">
            {trace.claim}
          </p>
        </Panel>
        <Panel>
          <div className="flex items-center justify-between gap-2">
            <PanelTitle>What the evidence supports</PanelTitle>
            <a
              href="#evidence-map"
              className="inline-flex items-center gap-1 text-[0.68rem] font-medium text-accent underline-offset-2 hover:underline"
            >
              View evidence
              <ArrowRight className="size-3" />
            </a>
          </div>
          <p className="mt-2 font-serif text-lg leading-snug text-foreground text-pretty">
            {f.supportedWording || "No wording was proposed."}
          </p>
        </Panel>
      </div>

      {/* Internal research score. The backend serves it only when its research view is enabled. */}
      {score && (
        <div className="mt-4 rounded-xl border border-dashed border-border p-1">
          <AssessmentHistory trace={trace} score={score} />
        </div>
      )}

      {/* Finding narrative */}
      <Panel className="mt-4">
        <PanelTitle>Finding</PanelTitle>
        <p className="mt-3 text-[15px] leading-relaxed text-foreground text-pretty">
          {f.summary}
        </p>
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-border bg-secondary/40 p-3.5">
          <ShieldOff className="mt-0.5 size-4 shrink-0 text-unverifiable" />
          <div>
            <span className="text-[0.68rem] font-semibold uppercase tracking-wide text-muted-foreground">
              Source independence
            </span>
            <p className="mt-1 text-sm leading-relaxed text-foreground">
              {f.sourceIndependence}
            </p>
          </div>
        </div>
      </Panel>

      {/* Verification findings table */}
      <Panel className="mt-4">
        <PanelTitle>Verification checks</PanelTitle>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          The verification questions of the investigation and the calculations that code
          ran on figures quoted from the sources. A question is answered only when a passage
          answers it.
        </p>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full border-collapse text-left text-sm">
            <thead>
              <tr className="border-b border-border text-[0.68rem] uppercase tracking-wide text-muted-foreground">
                <th scope="col" className="py-2 pr-3 font-semibold">Verification check</th>
                <th scope="col" className="py-2 pr-3 font-semibold">Result</th>
                <th scope="col" className="py-2 pr-3 font-semibold">What it establishes</th>
              </tr>
            </thead>
            <tbody>
              {trace.checks.map((c) => {
                const s = checkStyle[c.status]
                const Icon = s.icon
                return (
                  <tr key={c.id} className="border-b border-border/60 align-top last:border-0">
                    <td className="py-3 pr-3 font-medium text-foreground">{c.name}</td>
                    <td className="py-3 pr-3">
                      <span className={cn("inline-flex items-center gap-1 font-medium", s.color)}>
                        <Icon className="size-3.5" />
                        {CHECK_LABELS[c.status]}
                      </span>
                    </td>
                    <td className="py-3 pr-3 leading-relaxed text-muted-foreground">
                      {c.detail}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Panel>

      {/* Questions that block vs. scope limits */}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Panel>
          <div className="flex items-center gap-2">
            <HelpCircle className="size-4 text-partial" />
            <PanelTitle>Questions that block a firm verdict</PanelTitle>
          </div>
          {f.unresolvedQuestions.length ? (
            <ul className="mt-3 flex flex-col gap-2.5">
              {f.unresolvedQuestions.map((q, i) => (
                <li key={i} className="flex gap-2 text-sm leading-relaxed text-foreground">
                  <span className="mt-1 size-1.5 shrink-0 rounded-full bg-partial" />
                  {q}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-muted-foreground">
              None — the claim was fully resolvable from the admitted evidence.
            </p>
          )}
        </Panel>
        <Panel>
          <PanelTitle>Limits on how broadly this applies</PanelTitle>
          <ul className="mt-3 flex flex-col gap-2.5">
            {f.limitations.map((l, i) => (
              <li key={i} className="flex gap-2 text-sm leading-relaxed text-muted-foreground">
                <span className="mt-1 size-1.5 shrink-0 rounded-full bg-border" />
                {l}
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      {/* SECONDARY: evidence map */}
      <Panel className="mt-4" id="evidence-map">
        <details>
          <summary className="flex cursor-pointer list-none items-center gap-2">
            <Network className="size-4 text-muted-foreground" />
            <PanelTitle>Evidence map</PanelTitle>
            <span className="ml-auto text-xs text-muted-foreground group-open:hidden">
              Expand
            </span>
          </summary>
          <div className="mt-4">
            <ProvenanceGraph trace={trace} />
          </div>
        </details>
      </Panel>

      {/* TERTIARY: technical trace */}
      <Panel className="mt-4">
        <details>
          <summary className="flex cursor-pointer list-none items-center gap-2">
            <Terminal className="size-4 text-muted-foreground" />
            <PanelTitle>Technical trace</PanelTitle>
            <span className="ml-auto text-xs text-muted-foreground">Expand</span>
          </summary>
          <div className="mt-2">
            <p className="text-xs leading-relaxed text-muted-foreground">
              The ordered execution pipeline — latency and per-stage outcomes —
              from document ingest to final assessment.
            </p>
            <ExecutionTrace trace={trace} />

            <dl className="mt-6 grid grid-cols-2 gap-x-6 gap-y-2 border-t border-border pt-4 text-sm sm:grid-cols-4">
              {[
                ["Model", trace.model],
                ["Model time (whole analysis)", `${(trace.durationMs / 1000).toFixed(1)}s`],
                ["Tokens (whole analysis)", trace.tokens.toLocaleString()],
                ["Review state", trace.reviewState],
              ].map(([k, v]) => (
                <div key={k} className="flex flex-col gap-0.5">
                  <dt className="text-[0.68rem] uppercase tracking-wide text-muted-foreground">
                    {k}
                  </dt>
                  <dd className="font-medium text-foreground">{v}</dd>
                </div>
              ))}
            </dl>

            <a
              href={`/api/backend/analyses/${trace.analysisId}/export`}
              className="mt-4 inline-flex items-center justify-center gap-1.5 rounded-lg border border-border bg-card px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
            >
              <Download className="size-3.5" />
              Export analysis JSON
            </a>
          </div>
        </details>
      </Panel>
    </div>
  )
}
