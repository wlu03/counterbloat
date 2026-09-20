"use client"

import { useMemo, useState } from "react"
import Link from "next/link"
import { ArrowUpDown, Search } from "lucide-react"
import { cn } from "@/lib/utils"
import { VERDICT_LABELS, type Trace, type Verdict } from "@/lib/types"
import { VerdictBadge } from "@/components/verdict-badge"
import { CoverageMeter } from "@/components/coverage-meter"

type SortKey = "recent" | "coverage" | "verdict"

const VERDICT_FILTERS: (Verdict | "all")[] = [
  "all",
  "contradicted",
  "partially_supported",
  "unverifiable",
  "supported",
]

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

function formatTime(iso: string) {
  return new Date(iso).toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
  })
}

const nodeStyles: Record<Verdict, string> = {
  supported: "bg-supported border-supported/30",
  contradicted: "bg-contradicted border-contradicted/30",
  partially_supported: "bg-partial border-partial/30",
  unverifiable: "bg-unverifiable border-unverifiable/30",
}

export function TracesExplorer({ traces }: { traces: Trace[] }) {
  const [query, setQuery] = useState("")
  const [verdict, setVerdict] = useState<Verdict | "all">("all")
  const [sort, setSort] = useState<SortKey>("recent")

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    let list = traces.filter((t) => {
      if (verdict !== "all" && t.verdict !== verdict) return false
      if (!q) return true
      return (
        t.claim.toLowerCase().includes(q) ||
        t.source.toLowerCase().includes(q) ||
        t.documentTitle.toLowerCase().includes(q) ||
        t.id.toLowerCase().includes(q) ||
        t.tags.some((tag) => tag.toLowerCase().includes(q))
      )
    })
    list = [...list].sort((a, b) => {
      if (sort === "coverage") return b.coverage - a.coverage
      if (sort === "verdict") return a.verdict.localeCompare(b.verdict)
      return b.createdAt.localeCompare(a.createdAt)
    })
    return list
  }, [traces, query, verdict, sort])

  return (
    <div>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative w-full sm:max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search claims, sources, tags, IDs"
            className="h-9 w-full rounded-lg border border-border bg-card pl-9 pr-3 text-sm outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/30"
          />
        </div>
        <button
          type="button"
          onClick={() =>
            setSort((s) =>
              s === "recent"
                ? "coverage"
                : s === "coverage"
                  ? "verdict"
                  : "recent",
            )
          }
          className="inline-flex h-9 items-center gap-1.5 self-start rounded-lg border border-border bg-card px-3 text-sm font-medium text-foreground transition-colors hover:bg-secondary sm:self-auto"
        >
          <ArrowUpDown className="size-3.5" />
          Sort:{" "}
          {sort === "recent"
            ? "Most recent"
            : sort === "coverage"
              ? "Coverage"
              : "Verdict"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-1.5">
        {VERDICT_FILTERS.map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setVerdict(v)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
              verdict === v
                ? "border-foreground bg-foreground text-background"
                : "border-border bg-card text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
          >
            {v === "all" ? "All" : VERDICT_LABELS[v]}
          </button>
        ))}
      </div>

      <p className="mt-4 text-xs text-muted-foreground">
        {filtered.length} {filtered.length === 1 ? "trace" : "traces"}
        {sort === "recent" && filtered.length > 1 && (
          <span> &middot; newest first</span>
        )}
      </p>

      {filtered.length === 0 ? (
        <div className="mt-2 rounded-xl border border-border bg-card px-5 py-12 text-center text-sm text-muted-foreground">
          No traces match your filters.
        </div>
      ) : (
        <ol className="relative mt-4">
          <span
            className="absolute left-[15px] top-2 bottom-2 w-px bg-border md:left-[19px]"
            aria-hidden="true"
          />
          {filtered.map((t, i) => (
            <li key={t.id} className="relative pl-11 md:pl-14">
              <span
                className={cn(
                  "absolute left-0 top-4 flex size-8 items-center justify-center rounded-full border-2 bg-card md:size-10",
                  nodeStyles[t.verdict].split(" ")[1],
                )}
                aria-hidden="true"
              >
                <span
                  className={cn(
                    "size-2.5 rounded-full",
                    nodeStyles[t.verdict].split(" ")[0],
                  )}
                />
              </span>
              <Link
                href={`/traces/${t.id}`}
                className="mb-3 block rounded-xl border border-border bg-card px-5 py-4 transition-colors hover:border-ring hover:bg-secondary/50"
              >
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                  <span className="font-mono tabular-nums text-foreground">
                    #{String(filtered.length - i).padStart(2, "0")}
                  </span>
                  <span aria-hidden="true">&middot;</span>
                  <span>{formatDate(t.createdAt)}</span>
                  <span className="text-muted-foreground/60">
                    {formatTime(t.createdAt)}
                  </span>
                  <span aria-hidden="true">&middot;</span>
                  <span className="font-mono text-[0.7rem]">{t.id}</span>
                </div>
                <div className="mt-2 flex flex-col gap-3 md:flex-row md:items-start md:justify-between md:gap-6">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1.5 flex flex-wrap items-center gap-2">
                      <VerdictBadge verdict={t.verdict} />
                    </div>
                    <p className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
                      {t.claim}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                      <span className="truncate">{t.source}</span>
                      {t.tags.slice(0, 2).map((tag) => (
                        <span
                          key={tag}
                          className="rounded bg-secondary px-1.5 py-0.5 font-mono text-[0.65rem]"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="md:w-44 md:shrink-0">
                    <span className="mb-1 block text-[0.65rem] uppercase tracking-wide text-muted-foreground">
                      Checklist coverage
                    </span>
                    <CoverageMeter value={t.coverage} />
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
