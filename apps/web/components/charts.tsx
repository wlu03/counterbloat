import { VERDICT_LABELS, type Verdict } from "@/lib/types"
import type { Aggregates } from "@/lib/live"

const VERDICT_COLOR: Record<Verdict, string> = {
  contradicted: "var(--contradicted)",
  partially_supported: "var(--partial)",
  supported: "var(--supported)",
  unverifiable: "var(--unverifiable)",
}

const VERDICT_ORDER: Verdict[] = [
  "contradicted",
  "partially_supported",
  "unverifiable",
  "supported",
]

export function VerdictDonut({
  counts,
  total,
}: {
  counts: Record<Verdict, number>
  total: number
}) {
  const radius = 60
  const circumference = 2 * Math.PI * radius
  let offset = 0
  const safeTotal = total || 1

  return (
    <div className="flex flex-col items-center gap-5 sm:flex-row sm:gap-7">
      <div className="relative shrink-0">
        <svg width="150" height="150" viewBox="0 0 150 150" className="-rotate-90">
          <circle
            cx="75"
            cy="75"
            r={radius}
            fill="none"
            stroke="var(--border)"
            strokeWidth="14"
          />
          {VERDICT_ORDER.map((v) => {
            const value = counts[v]
            if (!value) return null
            const fraction = value / safeTotal
            const dash = fraction * circumference
            const el = (
              <circle
                key={v}
                cx="75"
                cy="75"
                r={radius}
                fill="none"
                stroke={VERDICT_COLOR[v]}
                strokeWidth="14"
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={-offset}
              />
            )
            offset += dash
            return el
          })}
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-3xl font-semibold tabular-nums text-foreground">
            {total}
          </span>
          <span className="text-xs text-muted-foreground">traces</span>
        </div>
      </div>
      <ul className="flex w-full flex-col gap-2">
        {VERDICT_ORDER.map((v) => (
          <li key={v} className="flex items-center gap-2.5 text-sm">
            <span
              className="size-2.5 rounded-full"
              style={{ backgroundColor: VERDICT_COLOR[v] }}
              aria-hidden="true"
            />
            <span className="flex-1 text-muted-foreground">
              {VERDICT_LABELS[v]}
            </span>
            <span className="font-semibold tabular-nums text-foreground">
              {counts[v]}
            </span>
            <span className="w-10 text-right text-xs text-muted-foreground tabular-nums">
              {Math.round((counts[v] / safeTotal) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

export function VolumeBars({ daily }: { daily: Aggregates["daily"] }) {
  const max = Math.max(...daily.map((d) => d.count), 1)
  return (
    <div className="flex h-40 items-stretch gap-1.5">
      {daily.map((d) => (
        <div key={d.date} className="group flex h-full flex-1 flex-col items-center gap-2">
          <div className="flex w-full flex-1 items-end">
            <div
              className="w-full rounded-t-sm bg-foreground/80 transition-colors group-hover:bg-accent"
              style={{ height: `${(d.count / max) * 100}%` }}
              title={`${d.date}: ${d.count}`}
            />
          </div>
          <span className="text-[0.6rem] text-muted-foreground tabular-nums">
            {d.date.slice(5)}
          </span>
        </div>
      ))}
    </div>
  )
}

export function TagBars({ tags }: { tags: Aggregates["tagCounts"] }) {
  const max = Math.max(...tags.map((t) => t.count), 1)
  return (
    <ul className="flex flex-col gap-3">
      {tags.slice(0, 7).map((t) => (
        <li key={t.tag} className="flex items-center gap-3 text-sm">
          <span className="w-44 shrink-0 truncate font-mono text-xs text-muted-foreground">
            {t.tag}
          </span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-border">
            <div
              className="h-full rounded-full bg-accent/70"
              style={{ width: `${(t.count / max) * 100}%` }}
            />
          </div>
          <span className="w-6 text-right font-semibold tabular-nums text-foreground">
            {t.count}
          </span>
        </li>
      ))}
    </ul>
  )
}
