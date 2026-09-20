"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  Search,
  Play,
  FileText,
  Mic,
  CheckCircle2,
  Loader2,
  ChevronRight,
  ChevronDown,
  AlertTriangle,
  MinusCircle,
  RotateCcw,
  XCircle,
  ExternalLink,
  Clock,
  Coins,
  Wrench,
  Flag,
  Check,
  ArrowRight,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { listCalls, startRun, waitForLedger } from "@/lib/calls"
import { Panel, PanelTitle } from "@/components/panel"
import {
  generateRunTrace,
  SECTOR_LABELS,
  CLAIM_TYPE_LABELS,
  LEDGER_VERDICT_LABELS,
  type TranscriptRecord,
  type Sector,
  type Ledger,
  type LedgerClaim,
  type LedgerVerdict,
  type RunTrace,
  type RunStage,
  type StageStatus,
  type RunMode,
  type RunSummary,
} from "@/lib/transcripts"

type RunState = "idle" | "running" | "done"

const SECTOR_FILTERS: (Sector | "all")[] = [
  "all",
  "software_ai",
  "pharma",
  "consumer",
  "finance",
  "industrial",
]

const verdictClasses: Record<LedgerVerdict, string> = {
  overstated: "bg-contradicted-bg text-contradicted border-contradicted/25",
  supported: "bg-supported-bg text-supported border-supported/25",
  mixed: "bg-partial-bg text-partial border-partial/30",
  abstain: "bg-unverifiable-bg text-unverifiable border-unverifiable/25",
}

const verdictDot: Record<LedgerVerdict, string> = {
  overstated: "bg-contradicted",
  supported: "bg-supported",
  mixed: "bg-partial",
  abstain: "bg-unverifiable",
}

const verdictBar: Record<LedgerVerdict, string> = {
  overstated: "bg-contradicted",
  supported: "bg-supported",
  mixed: "bg-partial",
  abstain: "bg-unverifiable",
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

function edgarUrl(cik: string, filingKind: string) {
  const type = filingKind === "10-K" ? "10-K" : "10-Q"
  return `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=${cik}&type=${type}&dateb=&owner=include&count=10`
}

const CADENCE = 340

export function TranscriptWorkflow() {
  const [query, setQuery] = useState("")
  const [sector, setSector] = useState<Sector | "all">("all")
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [runState, setRunState] = useState<RunState>("idle")
  const [revealStep, setRevealStep] = useState(0)
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const [trace, setTrace] = useState<RunTrace | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [corrections, setCorrections] = useState(0)
  const [resolved, setResolved] = useState<Record<string, LedgerVerdict>>({})
  const [history, setHistory] = useState<RunSummary[]>([])
  const [runMode, setRunMode] = useState<RunMode>("fresh")
  const [records, setRecords] = useState<TranscriptRecord[]>([])
  const [loadError, setLoadError] = useState<string | null>(null)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])

  // The calls the backend has every part of: transcript, matching annual report, filed figures.
  useEffect(() => {
    let live = true
    listCalls()
      .then((calls) => {
        if (live) setRecords(calls as unknown as TranscriptRecord[])
      })
      .catch((error: Error) => {
        if (live) setLoadError(error.message)
      })
    return () => {
      live = false
    }
  }, [])

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    return records.filter((t) => {
      if (sector !== "all" && t.sector !== sector) return false
      if (!q) return true
      return (
        t.company.toLowerCase().includes(q) ||
        t.ticker.toLowerCase().includes(q) ||
        t.period.toLowerCase().includes(q) ||
        t.summary.toLowerCase().includes(q)
      )
    })
  }, [query, sector, records])

  const selected = useMemo(
    () => records.find((t) => t.id === selectedId) ?? null,
    [selectedId, records],
  )

  function resetRun() {
    timers.current.forEach(clearTimeout)
    timers.current = []
    setRunState("idle")
    setRevealStep(0)
    setLedger(null)
    setTrace(null)
    setAttempt(0)
    setCorrections(0)
    setResolved({})
    setHistory([])
  }

  function selectTranscript(t: TranscriptRecord) {
    resetRun()
    setSelectedId(t.id)
  }

  async function runWorkflow(record: TranscriptRecord, mode: RunMode) {
    timers.current.forEach(clearTimeout)
    timers.current = []

    // Error memory: corrections resolved in the review queue carry forward.
    const corr = mode === "corrections" ? Object.keys(resolved).length : corrections
    if (mode === "corrections") setCorrections(corr)

    const nextAttempt = attempt + 1
    // The backend reads the call, chases each claim into the filing, and scores what it finds.
    let nextLedger = ledger
    if (!nextLedger || mode === "fresh") {
      setRunState("running")
      try {
        await startRun(record.id)
        nextLedger = (await waitForLedger(record.id)) as unknown as Ledger
      } catch (error) {
        setLoadError((error as Error).message)
        setRunState("idle")
        return
      }
    }
    const nextTrace = generateRunTrace(record, nextLedger, nextAttempt, corr, mode)

    // Snapshot the finished run into history before overwriting.
    if (trace) {
      setHistory((h) => [
        ...h,
        {
          attempt: trace.attempt,
          mode: trace.mode,
          escalated: trace.escalated,
          recovered: trace.recovered,
          overstated: trace.overstated,
          abstained: trace.abstained,
          wallTimeMs: trace.wallTimeMs,
          toolCalls: trace.toolCalls,
          costUsd: trace.costUsd,
        },
      ])
    }

    setLedger(nextLedger)
    setTrace(nextTrace)
    setAttempt(nextAttempt)
    setRunMode(mode)
    setRunState("running")
    setRevealStep(0)

    // Which stages actually animate. "failed" re-runs only touch the stages
    // that were degraded/recovered/failed last time; the rest are reused.
    const order =
      mode === "failed"
        ? nextTrace.stages
            .map((s, i) => ({ s, i }))
            .filter((x) => x.s.status !== "ok" && x.s.status !== "skipped")
            .map((x) => x.i)
        : nextTrace.stages.map((_, i) => i)

    order.forEach((_, step) => {
      const t = setTimeout(() => setRevealStep(step + 1), step * CADENCE)
      timers.current.push(t)
    })
    const finish = setTimeout(() => {
      setRunState("done")
      setRevealStep(order.length)
    }, order.length * CADENCE)
    timers.current.push(finish)
  }

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,320px)_minmax(0,1fr)]">
      {/* Left: search + catalog */}
      <div className="flex flex-col gap-4">
        <Panel className="flex flex-col gap-3">
          <PanelTitle>Find a transcript</PanelTitle>
          <label className="flex items-center gap-2 rounded-lg border border-border bg-background px-3 py-2">
            <Search className="size-4 shrink-0 text-muted-foreground" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Company, ticker, or period"
              className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
              aria-label="Search transcripts"
            />
          </label>
          <div className="flex flex-wrap gap-1.5">
            {SECTOR_FILTERS.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setSector(s)}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                  sector === s
                    ? "border-foreground bg-foreground text-background"
                    : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {s === "all" ? "All sectors" : SECTOR_LABELS[s]}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            {filtered.length} recent earnings call
            {filtered.length === 1 ? "" : "s"} · EDGAR + Motley Fool archive
          </p>
        </Panel>

        <div className="flex flex-col gap-2">
          {filtered.map((t) => {
            const active = t.id === selectedId
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => selectTranscript(t)}
                className={cn(
                  "group rounded-xl border bg-card p-3.5 text-left transition-colors",
                  active
                    ? "border-foreground ring-1 ring-foreground/10"
                    : "border-border hover:border-foreground/40",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded-md border border-border px-1.5 py-0.5 font-mono text-xs font-semibold text-foreground">
                      {t.ticker}
                    </span>
                    <span className="font-serif text-[0.95rem] text-foreground">
                      {t.company}
                    </span>
                  </div>
                  <ChevronRight
                    className={cn(
                      "size-4 shrink-0 text-muted-foreground transition-transform",
                      active && "translate-x-0.5 text-foreground",
                    )}
                  />
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                  <span>{t.period}</span>
                  <span aria-hidden>·</span>
                  <span>{formatDate(t.callDate)}</span>
                  <span aria-hidden>·</span>
                  <span>{SECTOR_LABELS[t.sector]}</span>
                </div>
                <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                  {t.summary}
                </p>
                <div className="mt-2 flex flex-wrap gap-1">
                  {t.docs.map((d) => (
                    <span
                      key={d}
                      className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[0.68rem] text-muted-foreground"
                    >
                      {d === "audio" ? (
                        <Mic className="size-3" />
                      ) : (
                        <FileText className="size-3" />
                      )}
                      {d}
                    </span>
                  ))}
                </div>
              </button>
            )
          })}
          {filtered.length === 0 && (
            <p className="rounded-xl border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              No transcripts match your search.
            </p>
          )}
        </div>
      </div>

      {/* Right: detail + run + results */}
      <div className="flex min-w-0 flex-col gap-5">
        {!selected && (
          <Panel className="flex min-h-[320px] flex-col items-center justify-center gap-2 text-center">
            <Search className="size-6 text-muted-foreground" />
            <p className="font-serif text-lg text-foreground">
              Select a transcript to begin
            </p>
            <p className="max-w-sm text-sm text-muted-foreground">
              Pick a recent earnings call from the archive. The engine extracts
              every executive claim, chases each into the matching filing, and
              scores it for overstatement.
            </p>
          </Panel>
        )}

        {selected && (
          <>
            <TranscriptCard
              record={selected}
              runState={runState}
              trace={trace}
              resolvedCount={Object.keys(resolved).length}
              onRun={(mode) => runWorkflow(selected, mode)}
            />

            {runState !== "idle" && trace && (
              <RunSummaryStrip trace={trace} runState={runState} />
            )}

            {runState !== "idle" && trace && (
              <PipelineTrace
                trace={trace}
                revealStep={revealStep}
                runState={runState}
                mode={runMode}
              />
            )}

            {runState === "done" && ledger && trace && (
              <>
                <ClaimLedger ledger={ledger} />
                <ReviewQueue
                  ledger={ledger}
                  trace={trace}
                  record={selected}
                  resolved={resolved}
                  onResolve={(id, v) =>
                    setResolved((r) => ({ ...r, [id]: v }))
                  }
                />
                <SignalRanking ledger={ledger} />
                {history.length > 0 && (
                  <RunHistory history={history} current={trace} />
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Transcript card + run controls                                     */
/* ------------------------------------------------------------------ */

function TranscriptCard({
  record,
  runState,
  trace,
  resolvedCount,
  onRun,
}: {
  record: TranscriptRecord
  runState: RunState
  trace: RunTrace | null
  resolvedCount: number
  onRun: (mode: RunMode) => void
}) {
  const running = runState === "running"
  const done = runState === "done"
  const hasDegraded =
    trace?.stages.some(
      (s) => s.status === "degraded" || s.status === "recovered" || s.status === "failed",
    ) ?? false

  return (
    <Panel className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="rounded-md border border-border px-1.5 py-0.5 font-mono text-xs font-semibold text-foreground">
              {record.ticker}
            </span>
            <h2 className="font-serif text-xl text-foreground">{record.company}</h2>
          </div>
          <p className="mt-1 text-sm text-muted-foreground">
            {record.period} earnings call · {formatDate(record.callDate)} · CIK{" "}
            {record.cik}
          </p>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
            <span>{record.source}</span>
            <span aria-hidden>·</span>
            <span>{record.executiveCount} execs</span>
            <span aria-hidden>·</span>
            <span>{record.analystCount} analysts</span>
            <span aria-hidden>·</span>
            <span>{record.wordCount.toLocaleString()} words</span>
          </div>
        </div>

        {!done ? (
          <button
            type="button"
            onClick={() => onRun("fresh")}
            disabled={running}
            className={cn(
              "inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors",
              running
                ? "cursor-not-allowed bg-secondary text-muted-foreground"
                : "bg-foreground text-background hover:bg-foreground/90",
            )}
          >
            {running ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Play className="size-4" />
            )}
            {running ? "Running…" : "Run overstatement analysis"}
          </button>
        ) : (
          <div className="flex flex-wrap items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => onRun("fresh")}
              className="inline-flex items-center gap-1.5 rounded-lg bg-foreground px-3 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90"
            >
              <RotateCcw className="size-4" />
              Re-run
            </button>
            <button
              type="button"
              onClick={() => onRun("corrections")}
              disabled={resolvedCount === 0}
              title={
                resolvedCount === 0
                  ? "Resolve items in the review queue first"
                  : undefined
              }
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                resolvedCount === 0
                  ? "cursor-not-allowed border-border text-muted-foreground"
                  : "border-foreground/30 text-foreground hover:bg-secondary",
              )}
            >
              <Check className="size-4" />
              Re-run with {resolvedCount} correction{resolvedCount === 1 ? "" : "s"}
            </button>
            <button
              type="button"
              onClick={() => onRun("failed")}
              disabled={!hasDegraded}
              title={hasDegraded ? undefined : "No degraded stages to re-run"}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
                !hasDegraded
                  ? "cursor-not-allowed border-border text-muted-foreground"
                  : "border-partial/40 text-partial hover:bg-partial-bg",
              )}
            >
              <AlertTriangle className="size-4" />
              Re-run failed stages
            </button>
          </div>
        )}
      </div>
    </Panel>
  )
}

/* ------------------------------------------------------------------ */
/* Run summary strip                                                   */
/* ------------------------------------------------------------------ */

function RunSummaryStrip({
  trace,
  runState,
}: {
  trace: RunTrace
  runState: RunState
}) {
  const wallSeconds = (trace.wallTimeMs / 1000).toFixed(1)
  return (
    <Panel className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PanelTitle>
          Run #{trace.attempt}
          <span className="ml-2 font-sans text-xs font-normal capitalize text-muted-foreground">
            {trace.mode === "fresh"
              ? "full run"
              : trace.mode === "corrections"
                ? "corrections applied"
                : "failed stages only"}
          </span>
        </PanelTitle>
        {runState === "running" && (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <Loader2 className="size-3.5 animate-spin" /> executing…
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <RunStat icon={Flag} label="Claims scored" value={String(trace.funnel.scored)} />
        <RunStat
          icon={FileText}
          label="Evidence"
          value={String(trace.stages.length ? sumEvidence(trace) : 0)}
        />
        <RunStat
          icon={AlertTriangle}
          label="To review"
          value={String(trace.escalated + trace.abstained)}
          tone={trace.escalated + trace.abstained > 0 ? "warn" : undefined}
        />
        <RunStat icon={Wrench} label="Tool calls" value={String(trace.toolCalls)} />
        <RunStat icon={Clock} label="Wall time" value={`${wallSeconds}s`} />
        <RunStat icon={Coins} label="Est. cost" value={`$${trace.costUsd.toFixed(3)}`} />
      </div>
    </Panel>
  )
}

function sumEvidence(trace: RunTrace) {
  const s7 = trace.stages.find((s) => s.id === "s7")
  const m = s7?.events[0]?.match(/(\d+) evidence/)
  return m ? Number(m[1]) : trace.funnel.scored * 2
}

function RunStat({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof Flag
  label: string
  value: string
  tone?: "warn"
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-background px-3 py-2.5">
      <span className="inline-flex items-center gap-1.5 text-[0.66rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        <Icon className="size-3.5" />
        {label}
      </span>
      <span
        className={cn(
          "font-serif text-xl leading-none",
          tone === "warn" ? "text-partial" : "text-foreground",
        )}
      >
        {value}
      </span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Pipeline trace                                                      */
/* ------------------------------------------------------------------ */

const statusMeta: Record<
  StageStatus,
  { label: string; dot: string; text: string; Icon: typeof CheckCircle2 }
> = {
  ok: { label: "OK", dot: "bg-supported", text: "text-supported", Icon: CheckCircle2 },
  recovered: {
    label: "Recovered",
    dot: "bg-partial",
    text: "text-partial",
    Icon: RotateCcw,
  },
  degraded: {
    label: "Degraded",
    dot: "bg-partial",
    text: "text-partial",
    Icon: AlertTriangle,
  },
  skipped: {
    label: "Skipped",
    dot: "bg-muted-foreground/50",
    text: "text-muted-foreground",
    Icon: MinusCircle,
  },
  failed: {
    label: "Failed",
    dot: "bg-contradicted",
    text: "text-contradicted",
    Icon: XCircle,
  },
}

function PipelineTrace({
  trace,
  revealStep,
  runState,
  mode,
}: {
  trace: RunTrace
  revealStep: number
  runState: RunState
  mode: RunMode
}) {
  // Order of animated stages (must mirror runWorkflow).
  const animatedIdx = useMemo(
    () =>
      mode === "failed"
        ? trace.stages
            .map((s, i) => ({ s, i }))
            .filter((x) => x.s.status !== "ok" && x.s.status !== "skipped")
            .map((x) => x.i)
        : trace.stages.map((_, i) => i),
    [trace, mode],
  )
  const posOf = useMemo(() => {
    const m = new Map<number, number>()
    animatedIdx.forEach((idx, pos) => m.set(idx, pos))
    return m
  }, [animatedIdx])

  return (
    <Panel className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PanelTitle>Pipeline trace</PanelTitle>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.7rem]">
          {(["ok", "recovered", "degraded", "skipped"] as StageStatus[]).map((s) => (
            <span key={s} className="inline-flex items-center gap-1.5">
              <span className={cn("size-2 rounded-full", statusMeta[s].dot)} />
              <span className="text-muted-foreground">{statusMeta[s].label}</span>
            </span>
          ))}
        </div>
      </div>

      <FunnelStrip funnel={trace.funnel} />

      <ol className="relative flex flex-col">
        {/* connecting spine */}
        <span
          className="absolute left-[11px] top-2 bottom-2 w-px bg-border"
          aria-hidden
        />
        {trace.stages.map((stage, i) => {
          const pos = posOf.get(i)
          const isAnimated = pos !== undefined
          const cached = mode === "failed" && !isAnimated
          const shown =
            runState === "done" || cached || (pos !== undefined && pos < revealStep)
          const activeStage =
            runState === "running" && pos !== undefined && pos === revealStep
          return (
            <StageRow
              key={stage.id}
              stage={stage}
              index={i}
              shown={shown}
              active={activeStage}
              cached={cached}
            />
          )
        })}
      </ol>

      {!trace.hasBaseline && (
        <p className="rounded-lg border border-partial/30 bg-partial-bg/60 px-3 py-2 text-xs leading-relaxed text-foreground/80">
          <AlertTriangle className="mr-1.5 inline size-3.5 align-text-bottom text-partial" />
          This run had only the <strong>{trace.filingKind}</strong>. drift-tracker
          and novelty-checker need a 10-K baseline to diff against, so both ran
          degraded — the stage is labelled with the filing actually used, not a
          generic 10-K.
        </p>
      )}
    </Panel>
  )
}

function FunnelStrip({ funnel }: { funnel: RunTrace["funnel"] }) {
  const steps = [
    { label: "Extracted", value: funnel.extracted, tone: "text-foreground" },
    { label: "Testable", value: funnel.testable, tone: "text-foreground" },
    { label: "Scored", value: funnel.scored, tone: "text-foreground" },
    { label: "Abstained", value: funnel.abstained, tone: "text-unverifiable" },
  ]
  const max = funnel.extracted || 1
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="flex items-center gap-2">
        {steps.map((s, i) => (
          <div key={s.label} className="flex min-w-0 flex-1 items-center gap-2">
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-1">
                <span className="text-[0.66rem] font-semibold uppercase tracking-[0.08em] text-muted-foreground">
                  {s.label}
                </span>
                <span className={cn("font-serif text-base leading-none", s.tone)}>
                  {s.value}
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-secondary">
                <div
                  className={cn(
                    "h-full rounded-full",
                    s.label === "Abstained" ? "bg-unverifiable" : "bg-foreground/70",
                  )}
                  style={{ width: `${Math.max(4, (s.value / max) * 100)}%` }}
                />
              </div>
            </div>
            {i < steps.length - 1 && (
              <ArrowRight className="size-3.5 shrink-0 text-muted-foreground/60" />
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function StageRow({
  stage,
  index,
  shown,
  active,
  cached,
}: {
  stage: RunStage
  index: number
  shown: boolean
  active: boolean
  cached: boolean
}) {
  const [open, setOpen] = useState(false)
  const meta = statusMeta[stage.status]
  const hasDetail = stage.events.length > 0 || (stage.agents && stage.agents.length > 0)
  const durLabel = stage.status === "skipped" ? "—" : `${(stage.durationMs / 1000).toFixed(1)}s`

  return (
    <li className="relative pl-8">
      {/* node */}
      <span className="absolute left-0 top-2.5 flex size-6 items-center justify-center">
        {active ? (
          <Loader2 className="size-5 animate-spin text-foreground" />
        ) : shown ? (
          <meta.Icon className={cn("size-5", meta.text)} />
        ) : (
          <span className="block size-3.5 rounded-full border border-border bg-background" />
        )}
      </span>

      <div
        className={cn(
          "flex flex-col rounded-lg border px-3 py-2 transition-colors",
          active
            ? "border-foreground/40 bg-secondary/50"
            : shown
              ? "border-transparent"
              : "border-transparent opacity-50",
        )}
      >
        <button
          type="button"
          onClick={() => hasDetail && shown && setOpen((o) => !o)}
          className="flex w-full items-start gap-2 text-left"
          aria-expanded={open}
          disabled={!hasDetail || !shown}
        >
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
              <span
                className={cn(
                  "text-sm font-medium",
                  shown || active ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {stage.name}
              </span>
              {shown && (
                <span
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-1.5 py-px text-[0.62rem] font-medium uppercase tracking-wide",
                    meta.text,
                    stage.status === "ok"
                      ? "border-supported/25 bg-supported-bg"
                      : stage.status === "skipped"
                        ? "border-border bg-secondary/50"
                        : stage.status === "failed"
                          ? "border-contradicted/25 bg-contradicted-bg"
                          : "border-partial/30 bg-partial-bg",
                  )}
                >
                  {cached ? "Reused" : meta.label}
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              {stage.detail}
            </p>
          </div>
          {shown && (
            <div className="flex shrink-0 items-center gap-3 pt-0.5">
              <span className="hidden text-right font-mono text-[0.7rem] text-muted-foreground sm:block">
                {durLabel}
                {stage.toolCalls > 0 && (
                  <span className="block">{stage.toolCalls} calls</span>
                )}
              </span>
              {hasDetail && (
                <ChevronDown
                  className={cn(
                    "size-4 shrink-0 text-muted-foreground transition-transform",
                    open && "rotate-180",
                  )}
                />
              )}
            </div>
          )}
        </button>

        {open && shown && (
          <div className="mt-2 flex flex-col gap-2 border-t border-border pt-2">
            {stage.events.map((e, i) => (
              <p
                key={i}
                className="flex items-start gap-2 text-xs leading-relaxed text-foreground/80"
              >
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-muted-foreground/50" />
                {e}
              </p>
            ))}
            {stage.agents && (
              <div className="mt-1 flex flex-col gap-1.5">
                {stage.agents.map((a) => {
                  const am = statusMeta[a.status]
                  return (
                    <div
                      key={a.agent}
                      className="flex items-start gap-2.5 rounded-lg border border-border bg-background px-2.5 py-2"
                    >
                      <span
                        className={cn("mt-1 size-2 shrink-0 rounded-full", am.dot)}
                        aria-hidden
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-x-2 text-xs">
                          <span className="font-mono font-medium text-foreground">
                            {a.agent}
                          </span>
                          <span className="rounded border border-border px-1 py-px text-[0.6rem] uppercase tracking-wide text-muted-foreground">
                            {a.tier.replace("_", " ")}
                          </span>
                          <span className={cn("font-medium", am.text)}>
                            {am.label}
                          </span>
                          <span className="font-mono text-muted-foreground">
                            {a.calls} call{a.calls === 1 ? "" : "s"}
                          </span>
                        </div>
                        {a.note && (
                          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                            {a.note}
                          </p>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </li>
  )
}

/* ------------------------------------------------------------------ */
/* Claim ledger (the deliverable)                                      */
/* ------------------------------------------------------------------ */

function ClaimLedger({ ledger }: { ledger: Ledger }) {
  const [openId, setOpenId] = useState<string | null>(null)
  const counts = useMemo(() => {
    const c: Record<LedgerVerdict, number> = {
      overstated: 0,
      supported: 0,
      mixed: 0,
      abstain: 0,
    }
    ledger.claims.forEach((cl) => (c[cl.verdict] += 1))
    return c
  }, [ledger])

  return (
    <Panel className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PanelTitle>Claim ledger</PanelTitle>
        <div className="flex flex-wrap gap-3 text-xs">
          {(Object.keys(counts) as LedgerVerdict[]).map((v) => (
            <span key={v} className="inline-flex items-center gap-1.5">
              <span className={cn("size-2 rounded-full", verdictDot[v])} />
              <span className="text-muted-foreground">
                {LEDGER_VERDICT_LABELS[v]} · {counts[v]}
              </span>
            </span>
          ))}
        </div>
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">
        The deliverable: every executive claim, its calibrated probability of
        being overstated, and the filing evidence behind that call. Expand a row
        for the feature breakdown and matched spans.
      </p>
      <div className="flex flex-col divide-y divide-border">
        {ledger.claims.map((claim) => (
          <LedgerRow
            key={claim.id}
            claim={claim}
            open={openId === claim.id}
            onToggle={() =>
              setOpenId((cur) => (cur === claim.id ? null : claim.id))
            }
          />
        ))}
      </div>
    </Panel>
  )
}

function LedgerRow({
  claim,
  open,
  onToggle,
}: {
  claim: LedgerClaim
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="py-3 first:pt-0 last:pb-0">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-3 text-left"
        aria-expanded={open}
      >
        <span
          className={cn(
            "mt-1 inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[0.66rem] font-medium uppercase tracking-wide",
            verdictClasses[claim.verdict],
          )}
        >
          <span className="size-1.5 rounded-full bg-current" aria-hidden />
          {LEDGER_VERDICT_LABELS[claim.verdict]}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm leading-relaxed text-foreground">
            {claim.text}
          </span>
          <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
            <span>{claim.speaker}</span>
            <span aria-hidden>·</span>
            <span>{claim.segment === "qa" ? "Q&A" : "Prepared"}</span>
            <span aria-hidden>·</span>
            <span>{CLAIM_TYPE_LABELS[claim.claimType]}</span>
            <span aria-hidden>·</span>
            <span>{claim.topic}</span>
          </span>
        </span>
        <span className="shrink-0 text-right">
          <span className="block font-serif text-lg leading-none text-foreground">
            {Math.round(claim.probability * 100)}%
          </span>
          <span className="text-[0.66rem] uppercase tracking-wide text-muted-foreground">
            p(overstated)
          </span>
        </span>
      </button>

      {open && (
        <div className="mt-3 flex flex-col gap-3 pl-1">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MiniMetric label="Inflation" value={`${claim.rhetoricalInflation}`} />
            <MiniMetric label="Evidence gap" value={`${claim.evidenceGap}`} />
            <MiniMetric label="Specificity" value={`${claim.specificity}/6`} />
            <MiniMetric label="Hedging Δ" value={claim.hedgingDelta.toFixed(2)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <span className="text-[0.68rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
              Evidence
            </span>
            {claim.evidence.map((ev, i) => (
              <div
                key={i}
                className="flex items-start gap-2.5 rounded-lg border border-border bg-background px-3 py-2"
              >
                <StanceDot stance={ev.stance} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 text-xs">
                    <span className="font-mono font-medium text-foreground">
                      {ev.agent}
                    </span>
                    <span className="rounded border border-border px-1 py-px text-[0.62rem] uppercase tracking-wide text-muted-foreground">
                      {ev.tier.replace("_", " ")}
                    </span>
                    <span className="capitalize text-muted-foreground">
                      {ev.stance.replace("_", " ")}
                    </span>
                    <span className="text-muted-foreground">
                      · match {ev.matchScore.toFixed(2)}
                    </span>
                  </div>
                  {ev.span ? (
                    <p className="mt-0.5 text-xs leading-relaxed text-foreground/80">
                      “{ev.span}”
                    </p>
                  ) : (
                    <p className="mt-0.5 text-xs italic text-muted-foreground">
                      No matching span returned — a missing match is data, not a
                      paraphrase.
                    </p>
                  )}
                  {ev.accession && (
                    <p className="mt-0.5 font-mono text-[0.66rem] text-muted-foreground">
                      {ev.accession}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-background px-2.5 py-1.5">
      <span className="block text-[0.62rem] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
        {label}
      </span>
      <span className="font-serif text-base text-foreground">{value}</span>
    </div>
  )
}

function StanceDot({
  stance,
}: {
  stance: LedgerClaim["evidence"][number]["stance"]
}) {
  const cls =
    stance === "contradicts"
      ? "bg-contradicted"
      : stance === "supports"
        ? "bg-supported"
        : stance === "not_found"
          ? "bg-muted-foreground/40"
          : "bg-partial"
  return <span className={cn("mt-1 size-2 shrink-0 rounded-full", cls)} aria-hidden />
}

/* ------------------------------------------------------------------ */
/* Review queue                                                        */
/* ------------------------------------------------------------------ */

function ReviewQueue({
  ledger,
  trace,
  record,
  resolved,
  onResolve,
}: {
  ledger: Ledger
  trace: RunTrace
  record: TranscriptRecord
  resolved: Record<string, LedgerVerdict>
  onResolve: (id: string, v: LedgerVerdict) => void
}) {
  const queue = ledger.claims.filter((c) => c.verdict === "abstain")
  if (queue.length === 0) return null
  const resolvedCount = queue.filter((c) => resolved[c.id]).length

  return (
    <Panel className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <PanelTitle>
          Review queue
          <span className="ml-2 font-sans text-xs font-normal text-muted-foreground">
            {resolvedCount}/{queue.length} resolved
          </span>
        </PanelTitle>
        {resolvedCount > 0 && (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-supported/25 bg-supported-bg px-2 py-0.5 text-[0.7rem] font-medium text-supported">
            <Check className="size-3" />
            Applied on next run as corrections
          </span>
        )}
      </div>
      <p className="text-sm leading-relaxed text-muted-foreground">
        The engine abstained on these — evidence was too thin to score. A human
        verdict here both clears the claim and writes to the error memory, so the
        next run recovers instead of escalating.
      </p>
      <div className="flex flex-col gap-2.5">
        {queue.map((claim) => {
          const decision = resolved[claim.id]
          const spans = claim.evidence.filter((e) => e.span)
          return (
            <div
              key={claim.id}
              className={cn(
                "rounded-xl border p-3.5 transition-colors",
                decision
                  ? "border-supported/30 bg-supported-bg/40"
                  : "border-border bg-background",
              )}
            >
              <p className="text-sm leading-relaxed text-foreground">{claim.text}</p>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
                <span>{claim.speaker}</span>
                <span aria-hidden>·</span>
                <span>{claim.segment === "qa" ? "Q&A" : "Prepared"}</span>
                <span aria-hidden>·</span>
                <span>{CLAIM_TYPE_LABELS[claim.claimType]}</span>
              </div>

              {spans.length > 0 ? (
                <div className="mt-2 flex flex-col gap-1.5">
                  {spans.map((ev, i) => (
                    <div
                      key={i}
                      className="rounded-lg border border-border bg-card px-2.5 py-1.5"
                    >
                      <div className="flex flex-wrap items-center gap-x-2 text-[0.7rem]">
                        <span className="font-mono font-medium text-foreground">
                          {ev.agent}
                        </span>
                        <a
                          href={edgarUrl(record.cik, trace.filingKind)}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-accent-foreground underline decoration-dotted underline-offset-2 hover:text-foreground"
                        >
                          {ev.accession ?? trace.filingKind}
                          <ExternalLink className="size-3" />
                        </a>
                      </div>
                      <p className="mt-0.5 text-xs leading-relaxed text-foreground/75">
                        “{ev.span}”
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-xs italic text-muted-foreground">
                  No matched spans — reviewer must pull the filing directly.
                </p>
              )}

              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                {decision ? (
                  <>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium",
                        verdictClasses[decision],
                      )}
                    >
                      <Check className="size-3" />
                      Marked {LEDGER_VERDICT_LABELS[decision]}
                    </span>
                    <button
                      type="button"
                      onClick={() => onResolve(claim.id, "abstain")}
                      className="text-xs text-muted-foreground underline underline-offset-2 hover:text-foreground"
                    >
                      Undo
                    </button>
                  </>
                ) : (
                  <>
                    <span className="text-[0.7rem] font-semibold uppercase tracking-wide text-muted-foreground">
                      Verdict:
                    </span>
                    <ReviewButton
                      label="Overstated"
                      tone="contradicted"
                      onClick={() => onResolve(claim.id, "overstated")}
                    />
                    <ReviewButton
                      label="Supported"
                      tone="supported"
                      onClick={() => onResolve(claim.id, "supported")}
                    />
                    <ReviewButton
                      label="Mixed"
                      tone="partial"
                      onClick={() => onResolve(claim.id, "mixed")}
                    />
                  </>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </Panel>
  )
}

function ReviewButton({
  label,
  tone,
  onClick,
}: {
  label: string
  tone: "contradicted" | "supported" | "partial"
  onClick: () => void
}) {
  const cls =
    tone === "contradicted"
      ? "border-contradicted/30 text-contradicted hover:bg-contradicted-bg"
      : tone === "supported"
        ? "border-supported/30 text-supported hover:bg-supported-bg"
        : "border-partial/30 text-partial hover:bg-partial-bg"
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
        cls,
      )}
    >
      {label}
    </button>
  )
}

/* ------------------------------------------------------------------ */
/* Signal ranking (replaces the 5-point scatter)                       */
/* ------------------------------------------------------------------ */

function SignalRanking({ ledger }: { ledger: Ledger }) {
  const ranked = useMemo(
    () => [...ledger.claims].sort((a, b) => b.probability - a.probability),
    [ledger],
  )
  return (
    <Panel className="flex flex-col gap-3">
      <PanelTitle>Signal ranking</PanelTitle>
      <p className="text-sm leading-relaxed text-muted-foreground">
        Two signals kept separate on purpose. <strong>Inflation</strong> is how
        loud the language is; <strong>evidence gap</strong> is whether anything
        in the filings actually contradicts it. Loud but corroborated is not the
        same as quiet but contradicted.
      </p>
      <div className="flex flex-col gap-2">
        {ranked.map((claim, i) => (
          <div
            key={claim.id}
            className="rounded-xl border border-border bg-background p-3"
          >
            <div className="flex items-start gap-3">
              <span className="mt-0.5 font-mono text-xs text-muted-foreground">
                {String(i + 1).padStart(2, "0")}
              </span>
              <span
                className={cn("mt-1.5 size-2 shrink-0 rounded-full", verdictDot[claim.verdict])}
                aria-hidden
              />
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-relaxed text-foreground">
                  {claim.text}
                </p>
                <div className="mt-2 flex flex-col gap-1.5">
                  <SignalBar
                    label="Inflation"
                    value={claim.rhetoricalInflation}
                    className="bg-foreground/70"
                  />
                  <SignalBar
                    label="Evidence gap"
                    value={claim.evidenceGap}
                    className={verdictBar[claim.verdict]}
                  />
                </div>
              </div>
              <span className="shrink-0 text-right">
                <span className="block font-serif text-lg leading-none text-foreground">
                  {Math.round(claim.probability * 100)}%
                </span>
                <span className="text-[0.62rem] uppercase tracking-wide text-muted-foreground">
                  overstated
                </span>
              </span>
            </div>
          </div>
        ))}
      </div>
    </Panel>
  )
}

function SignalBar({
  label,
  value,
  className,
}: {
  label: string
  value: number
  className: string
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="w-24 shrink-0 text-[0.66rem] uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
        <div
          className={cn("h-full rounded-full", className)}
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="w-7 shrink-0 text-right font-mono text-xs text-muted-foreground">
        {value}
      </span>
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* Run history + diff                                                  */
/* ------------------------------------------------------------------ */

function RunHistory({
  history,
  current,
}: {
  history: RunSummary[]
  current: RunTrace
}) {
  const rows: RunSummary[] = [
    ...history,
    {
      attempt: current.attempt,
      mode: current.mode,
      escalated: current.escalated,
      recovered: current.recovered,
      overstated: current.overstated,
      abstained: current.abstained,
      wallTimeMs: current.wallTimeMs,
      toolCalls: current.toolCalls,
      costUsd: current.costUsd,
    },
  ]
  return (
    <Panel className="flex flex-col gap-3">
      <PanelTitle>Run history</PanelTitle>
      <p className="text-sm leading-relaxed text-muted-foreground">
        Same company, successive runs. As reviewer corrections feed the error
        memory, escalations fall and the run gets cheaper — learning across runs,
        made visible.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="py-2 pr-3 font-semibold">Run</th>
              <th className="py-2 pr-3 font-semibold">Mode</th>
              <th className="py-2 pr-3 font-semibold">Escalated</th>
              <th className="py-2 pr-3 font-semibold">Recovered</th>
              <th className="py-2 pr-3 font-semibold">Wall time</th>
              <th className="py-2 pr-3 font-semibold">Cost</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const prev = i > 0 ? rows[i - 1] : null
              const escDelta = prev ? r.escalated - prev.escalated : 0
              return (
                <tr key={r.attempt} className="border-b border-border/60 last:border-0">
                  <td className="py-2 pr-3 font-mono">#{r.attempt}</td>
                  <td className="py-2 pr-3 capitalize text-muted-foreground">
                    {r.mode === "fresh"
                      ? "full"
                      : r.mode === "corrections"
                        ? "corrections"
                        : "failed only"}
                  </td>
                  <td className="py-2 pr-3">
                    <span className="inline-flex items-center gap-1.5">
                      {r.escalated}
                      {escDelta !== 0 && (
                        <span
                          className={cn(
                            "text-xs",
                            escDelta < 0 ? "text-supported" : "text-contradicted",
                          )}
                        >
                          {escDelta < 0 ? "▼" : "▲"}
                          {Math.abs(escDelta)}
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="py-2 pr-3">{r.recovered}</td>
                  <td className="py-2 pr-3 font-mono text-muted-foreground">
                    {(r.wallTimeMs / 1000).toFixed(1)}s
                  </td>
                  <td className="py-2 pr-3 font-mono text-muted-foreground">
                    ${r.costUsd.toFixed(3)}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  )
}
