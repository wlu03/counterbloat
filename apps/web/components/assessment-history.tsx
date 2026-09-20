"use client"

import { useMemo, useState } from "react"
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Check,
  FlaskConical,
  Minus,
  RotateCcw,
  TriangleAlert,
  X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import type { CheckStatus, Trace } from "@/lib/types"
import {
  buildAssessmentHistory,
  finalEstimate,
  toScore,
  type AssessmentUpdate,
  type ResearchScore,
} from "@/lib/assessment"
import { Panel, PanelTitle } from "@/components/panel"

const statusColor: Record<CheckStatus, string> = {
  pass: "var(--supported)",
  fail: "var(--contradicted)",
  warn: "var(--partial)",
  skip: "var(--muted-foreground)",
}

const statusText: Record<CheckStatus, string> = {
  pass: "text-supported",
  fail: "text-contradicted",
  warn: "text-partial",
  skip: "text-muted-foreground",
}

const statusIcon: Record<CheckStatus, typeof Check> = {
  pass: Check,
  fail: X,
  warn: TriangleAlert,
  skip: Minus,
}

// SVG plot geometry
const W = 640
const H = 260
const PAD = { left: 46, right: 18, top: 18, bottom: 36 }
const PLOT_W = W - PAD.left - PAD.right
const PLOT_H = H - PAD.top - PAD.bottom

function colorFor(u: AssessmentUpdate) {
  return u.kind === "prior" ? "var(--muted-foreground)" : statusColor[u.status!]
}

/** Distinct marker shapes so meaning survives without color (WCAG 1.4.1). */
function Marker({
  cx,
  cy,
  u,
  selected,
}: {
  cx: number
  cy: number
  u: AssessmentUpdate
  selected: boolean
}) {
  const c = colorFor(u)
  const r = selected ? 6 : 5
  let shape: React.ReactNode

  if (u.kind === "prior") {
    shape = <rect x={cx - r} y={cy - r} width={r * 2} height={r * 2} fill={c} />
  } else if (u.status === "pass") {
    shape = <circle cx={cx} cy={cy} r={r} fill={c} />
  } else if (u.status === "fail") {
    shape = (
      <g stroke={c} strokeWidth={2.4} strokeLinecap="round">
        <line x1={cx - r} y1={cy - r} x2={cx + r} y2={cy + r} />
        <line x1={cx - r} y1={cy + r} x2={cx + r} y2={cy - r} />
      </g>
    )
  } else if (u.status === "warn") {
    shape = (
      <polygon
        points={`${cx},${cy - r - 1} ${cx + r + 1},${cy + r} ${cx - r - 1},${cy + r}`}
        fill={c}
      />
    )
  } else {
    shape = (
      <line
        x1={cx - r}
        y1={cy}
        x2={cx + r}
        y2={cy}
        stroke={c}
        strokeWidth={2.6}
        strokeLinecap="round"
      />
    )
  }

  return (
    <>
      {selected && (
        <circle cx={cx} cy={cy} r={11} fill="none" stroke={c} strokeWidth={1.5} opacity={0.5} />
      )}
      {shape}
    </>
  )
}

const DIRECTION: Record<CheckStatus, string> = {
  fail: "Raises the score",
  pass: "Lowers the score",
  warn: "Leaves the score as it was",
  skip: "Not scored",
}

/** The internal research score of one finding. Rendered only when the backend serves one. */
export function AssessmentHistory({ trace, score }: { trace: Trace; score: ResearchScore }) {
  const full = useMemo(() => buildAssessmentHistory(score), [score])
  const [selected, setSelected] = useState(full.length - 1)
  const [excluded, setExcluded] = useState<Set<string>>(new Set())

  const sens = useMemo(
    () => (excluded.size ? buildAssessmentHistory(score, excluded) : null),
    [score, excluded],
  )

  const n = full.length
  const fullIndexByCheck = useMemo(() => {
    const m = new Map<string, number>()
    full.forEach((u, i) => u.checkId && m.set(u.checkId, i))
    return m
  }, [full])

  const x = (i: number) => (n <= 1 ? PAD.left + PLOT_W / 2 : PAD.left + (i / (n - 1)) * PLOT_W)
  const y = (p: number) => PAD.top + (1 - p) * PLOT_H

  // main step-after path
  const mainPath = full
    .map((u, i) =>
      i === 0
        ? `M ${x(0)} ${y(u.value)}`
        : `L ${x(i)} ${y(u.prev)} L ${x(i)} ${y(u.value)}`,
    )
    .join(" ")

  // sensitivity step-after path, aligned to the full-run x positions
  const sensX = (u: AssessmentUpdate) =>
    u.kind === "prior" ? x(0) : x(fullIndexByCheck.get(u.checkId!) ?? u.index)
  const sensPath = sens
    ? sens
        .map((u, i) =>
          i === 0
            ? `M ${sensX(u)} ${y(u.value)}`
            : `L ${sensX(u)} ${y(u.prev)} L ${sensX(u)} ${y(u.value)}`,
        )
        .join(" ")
    : null

  const sel = full[selected]
  const finalFull = finalEstimate(full)
  const finalSens = sens ? finalEstimate(sens) : null

  function toggleExclude(checkId: string) {
    setExcluded((prev) => {
      const next = new Set(prev)
      next.has(checkId) ? next.delete(checkId) : next.add(checkId)
      return next
    })
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[1.7fr_1fr] lg:items-start">
      {/* Chart + accessible table */}
      <Panel>
        <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
          <div>
            <PanelTitle>Internal research score</PanelTitle>
            <p className="mt-1 text-sm font-medium text-foreground">
              Raw uncalibrated score for the target {score.targetId}
            </p>
          </div>
          <span className="rounded-full border border-partial/40 bg-partial-bg px-2.5 py-1 text-[0.62rem] font-medium uppercase tracking-wide text-partial">
            Experimental · Evidence accumulator · {score.calibration}
          </span>
        </div>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          {score.hypothesis} Each source unit moves the score by the log-evidence a language
          model estimated for it. This is not a probability that the claim is false, and the
          finding does not use it. Select a point to inspect the update.
        </p>

        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="mt-4 w-full"
          role="img"
          aria-label="Step chart of the raw score after each source unit. An accessible table of the same values follows."
        >
          {/* gridlines + y labels */}
          {[0, 0.25, 0.5, 0.75, 1].map((p) => (
            <g key={p}>
              <line
                x1={PAD.left}
                y1={y(p)}
                x2={W - PAD.right}
                y2={y(p)}
                stroke="var(--border)"
                strokeWidth={1}
                strokeDasharray={p === 0 || p === 1 ? "0" : "3 3"}
              />
              <text
                x={PAD.left - 8}
                y={y(p) + 3}
                textAnchor="end"
                className="fill-muted-foreground"
                style={{ fontSize: 10, fontVariantNumeric: "tabular-nums" }}
              >
                {p.toFixed(2)}
              </text>
            </g>
          ))}

          {/* sensitivity line */}
          {sensPath && (
            <path
              d={sensPath}
              fill="none"
              stroke="var(--muted-foreground)"
              strokeWidth={1.6}
              strokeDasharray="5 4"
              opacity={0.8}
            />
          )}

          {/* main line */}
          <path d={mainPath} fill="none" stroke="var(--foreground)" strokeWidth={2} opacity={0.85} />

          {/* markers + hit targets + x labels */}
          {full.map((u, i) => {
            const cx = x(i)
            const cy = y(u.value)
            return (
              <g key={u.index}>
                <Marker cx={cx} cy={cy} u={u} selected={i === selected} />
                <text
                  x={cx}
                  y={H - PAD.bottom + 16}
                  textAnchor="middle"
                  className="fill-muted-foreground"
                  style={{ fontSize: 10, fontVariantNumeric: "tabular-nums" }}
                >
                  {u.kind === "prior" ? "prior" : i}
                </text>
                <circle
                  cx={cx}
                  cy={cy}
                  r={15}
                  fill="transparent"
                  className="cursor-pointer"
                  onClick={() => setSelected(i)}
                >
                  <title>
                    {u.label}: {toScore(u.value)}
                  </title>
                </circle>
              </g>
            )
          })}
        </svg>

        {sens && finalSens !== null && (
          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border border-dashed border-border bg-secondary/40 px-3 py-2 text-xs">
            <span className="font-medium text-foreground">Evidence sensitivity</span>
            <span className="text-muted-foreground">
              excluding {excluded.size} source unit{excluded.size === 1 ? "" : "s"}:
            </span>
            <span className="tabular-nums text-muted-foreground">
              final {toScore(finalFull)}{" "}
              <ArrowRight className="inline size-3 -translate-y-px" />{" "}
              <span className="font-semibold text-foreground">{toScore(finalSens)}</span>
            </span>
            <button
              type="button"
              onClick={() => setExcluded(new Set())}
              className="ml-auto inline-flex items-center gap-1 text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            >
              <RotateCcw className="size-3" />
              Reset
            </button>
          </div>
        )}

        {/* Accessible event table */}
        <table className="mt-4 w-full border-collapse text-left text-sm">
          <caption className="sr-only">
            Raw score after each source unit
          </caption>
          <thead>
            <tr className="border-b border-border text-[0.68rem] uppercase tracking-wide text-muted-foreground">
              <th scope="col" className="py-2 pr-2 font-semibold">#</th>
              <th scope="col" className="py-2 pr-2 font-semibold">Update</th>
              <th scope="col" className="py-2 pr-2 text-right font-semibold">Raw score</th>
              <th scope="col" className="py-2 text-right font-semibold">Change</th>
            </tr>
          </thead>
          <tbody>
            {full.map((u, i) => (
              <tr
                key={u.index}
                className={cn(
                  "border-b border-border/60 last:border-0",
                  i === selected && "bg-secondary/60",
                )}
              >
                <td className="py-1.5 pr-2 font-mono text-xs text-muted-foreground tabular-nums">
                  {u.kind === "prior" ? "—" : i}
                </td>
                <td className="py-1.5 pr-2">
                  <button
                    type="button"
                    onClick={() => setSelected(i)}
                    className="text-left font-medium text-foreground underline-offset-2 hover:underline"
                  >
                    {u.label}
                  </button>
                </td>
                <td className="py-1.5 pr-2 text-right font-semibold tabular-nums text-foreground">
                  {toScore(u.value)}
                </td>
                <td className="py-1.5 text-right tabular-nums">
                  {u.kind === "prior" ? (
                    <span className="text-muted-foreground">baseline</span>
                  ) : (
                    <DeltaLabel delta={u.delta} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>

      {/* Selected update detail */}
      <Panel className="lg:sticky lg:top-6">
        <PanelTitle>
          Selected update {sel.kind === "prior" ? "" : `— ${selected}`}
        </PanelTitle>

        <h3 className="mt-2 flex items-start gap-2 text-[15px] font-medium leading-snug text-foreground">
          {sel.kind === "prior" ? (
            <FlaskConical className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
          ) : (
            (() => {
              const Icon = statusIcon[sel.status!]
              return <Icon className={cn("mt-0.5 size-4 shrink-0", statusText[sel.status!])} />
            })()
          )}
          {sel.label}
        </h3>

        {sel.kind !== "prior" && (
          <span
            className={cn(
              "mt-1 inline-block text-[0.68rem] font-medium uppercase tracking-wide",
              statusText[sel.status!],
            )}
          >
            {DIRECTION[sel.status!]}
          </span>
        )}

        {/* transition */}
        <div className="mt-4 flex items-center gap-3 rounded-lg border border-border bg-secondary/40 px-3.5 py-3">
          <div className="flex flex-col">
            <span className="text-[0.62rem] uppercase tracking-wide text-muted-foreground">
              Previous
            </span>
            <span className="font-serif text-2xl leading-none text-muted-foreground tabular-nums">
              {toScore(sel.prev)}
            </span>
          </div>
          <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
          <div className="flex flex-col">
            <span className="text-[0.62rem] uppercase tracking-wide text-muted-foreground">
              New
            </span>
            <span className="font-serif text-2xl leading-none text-foreground tabular-nums">
              {toScore(sel.value)}
            </span>
          </div>
          <div className="ml-auto">
            <DeltaLabel delta={sel.delta} big />
          </div>
        </div>

        <dl className="mt-4 flex flex-col gap-3 text-sm">
          <div>
            <dt className="text-[0.68rem] font-semibold uppercase tracking-wide text-muted-foreground">
              Basis given by the scorer
            </dt>
            <dd className="mt-1 leading-relaxed text-foreground">{sel.detail}</dd>
          </div>
          <div>
            <dt className="text-[0.68rem] font-semibold uppercase tracking-wide text-muted-foreground">
              Evidence dependency
            </dt>
            <dd className="mt-1 leading-relaxed text-muted-foreground">
              {trace.evidence.some((e) => e.independent)
                ? "At least one admitted source is independent of the claimant."
                : "All admitted sources are self-reported; findings share the same observation base and do not independently corroborate one another."}
            </dd>
          </div>
        </dl>

        {sel.kind === "check" && (
          <button
            type="button"
            onClick={() => toggleExclude(sel.checkId!)}
            className={cn(
              "mt-4 inline-flex w-full items-center justify-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors",
              excluded.has(sel.checkId!)
                ? "border-accent/50 bg-accent/10 text-foreground hover:bg-accent/20"
                : "border-border bg-card text-foreground hover:bg-secondary",
            )}
          >
            <RotateCcw className="size-3.5" />
            {excluded.has(sel.checkId!) ? "Restore this source unit" : "Recompute without this source unit"}
          </button>
        )}
        <p className="mt-2 text-[0.68rem] leading-relaxed text-muted-foreground">
          Recomputes the same sum from the remaining recorded values. It changes nothing that
          is stored and does not affect the finding.
        </p>
      </Panel>
    </div>
  )
}

function DeltaLabel({ delta, big }: { delta: number; big?: boolean }) {
  const up = delta > 0
  const flat = Math.abs(delta) < 0.0005
  const Icon = up ? ArrowUp : ArrowDown
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 font-semibold tabular-nums",
        big ? "text-base" : "text-sm",
        flat ? "text-muted-foreground" : up ? "text-contradicted" : "text-supported",
      )}
    >
      {!flat && <Icon className={big ? "size-4" : "size-3"} />}
      {up ? "+" : ""}
      {delta.toFixed(3)}
    </span>
  )
}
