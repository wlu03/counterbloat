import {
  FileText,
  Quote,
  Search,
  FlaskConical,
  Sigma,
  Gavel,
  Check,
  X,
  TriangleAlert,
  Minus,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { CHECK_LABELS, type CheckStatus, type Trace } from "@/lib/types"
import { VERDICT_LABELS } from "@/lib/types"

type StageTone = "neutral" | "for" | "against" | "warn"

interface Stage {
  key: string
  icon: typeof FileText
  label: string
  detail: string
  tone: StageTone
  /** elapsed ms at which this stage completed */
  elapsedMs: number
  status?: CheckStatus
}

const toneRing: Record<StageTone, string> = {
  neutral: "border-border bg-card text-muted-foreground",
  for: "border-supported/40 bg-supported-bg text-supported",
  against: "border-contradicted/40 bg-contradicted-bg text-contradicted",
  warn: "border-partial/40 bg-partial-bg text-partial",
}

const checkTone: Record<CheckStatus, StageTone> = {
  pass: "for",
  fail: "against",
  warn: "warn",
  skip: "neutral",
}

const checkIcon: Record<CheckStatus, typeof Check> = {
  pass: Check,
  fail: X,
  warn: TriangleAlert,
  skip: Minus,
}

const PURPOSES: Record<string, { label: string; icon: typeof FileText }> = {
  route: { label: "Route a passage", icon: FileText },
  extract: { label: "Extract claims from a passage", icon: Quote },
  plan: { label: "Plan verification questions", icon: Search },
  discover: { label: "Search the web for sources", icon: Search },
  compress: { label: "Compress background passages", icon: FileText },
  analyze: { label: "Compare passages with the claim", icon: FlaskConical },
  update: { label: "Update the assessment", icon: Sigma },
  reassess: { label: "Assess from the active evidence", icon: Sigma },
  score: { label: "Score one source unit", icon: Sigma },
  review: { label: "Review against the original passages", icon: Gavel },
  report: { label: "Write the finding", icon: Gavel },
  replicate: { label: "Run the linked repository in Devin", icon: FlaskConical },
}

/** One stage per provider call that the backend recorded, with the latency it measured. Calls
 *  are recorded per analysis, so a document with several claims lists the calls of all of them. */
function buildStages(trace: Trace): Stage[] {
  let elapsed = 0
  const stages: Stage[] = trace.calls.map((call, i) => {
    elapsed += call.latencyMs
    const known = PURPOSES[call.purpose]
    return {
      key: `${i}`,
      icon: known?.icon ?? FileText,
      label: known?.label ?? call.purpose,
      detail: call.error
        ? `Failed: ${call.error}`
        : `${call.provider}${call.model ? ` ${call.model}` : ""} · ${call.tokens.toLocaleString()} tokens`,
      tone: call.error ? "against" : "neutral",
      elapsedMs: elapsed,
    }
  })
  stages.push({
    key: "verdict",
    icon: Gavel,
    label: `Finding — ${VERDICT_LABELS[trace.verdict]}`,
    detail: trace.tags.length ? `Mechanisms: ${trace.tags.join(", ")}` : "No mechanism was named.",
    tone:
      trace.verdict === "supported" ? "for" : trace.verdict === "contradicted" ? "against" : "warn",
    elapsedMs: elapsed,
  })
  return stages
}

function formatElapsed(ms: number) {
  return `${(ms / 1000).toFixed(1)}s`
}

export function ExecutionTrace({ trace }: { trace: Trace }) {
  const stages = buildStages(trace)

  return (
    <ol className="relative mt-4 flex flex-col">
      {/* connecting spine */}
      <span
        aria-hidden="true"
        className="absolute left-[15px] top-3 bottom-3 w-px bg-border"
      />
      {stages.map((stage, i) => {
        const Icon = stage.icon
        const CheckIcon = stage.status ? checkIcon[stage.status] : null
        return (
          <li key={stage.key} className="relative flex gap-4 pb-5 last:pb-0">
            <span
              className={cn(
                "relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full border",
                toneRing[stage.tone],
              )}
            >
              <Icon className="size-4" />
            </span>
            <div className="min-w-0 flex-1 pt-0.5">
              <div className="flex items-baseline justify-between gap-3">
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[0.7rem] text-muted-foreground tabular-nums">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <h3 className="text-sm font-medium leading-snug text-foreground">
                    {stage.label}
                  </h3>
                </div>
                <span className="shrink-0 font-mono text-[0.7rem] text-muted-foreground tabular-nums">
                  {formatElapsed(stage.elapsedMs)}
                </span>
              </div>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground text-pretty">
                {stage.detail}
              </p>
            </div>
          </li>
        )
      })}
    </ol>
  )
}
