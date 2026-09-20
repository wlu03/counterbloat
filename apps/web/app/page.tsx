import Link from "next/link"
import { ArrowUpRight } from "lucide-react"
import { AppShell } from "@/components/app-shell"
import { Panel, PanelTitle, StatCard } from "@/components/panel"
import { VerdictDonut, VolumeBars, TagBars } from "@/components/charts"
import { VerdictBadge } from "@/components/verdict-badge"
import { CoverageMeter } from "@/components/coverage-meter"
import { BackendNotice } from "@/components/backend-notice"
import { getAggregates, getTraces } from "@/lib/live"

export const dynamic = "force-dynamic"

export default async function OverviewPage() {
  const { traces, error } = await getTraces()
  const agg = getAggregates(traces)
  const recent = traces.slice(0, 5)

  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-8">
        <header className="mb-7">
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Analytics
          </p>
          <h1 className="mt-1 font-serif text-4xl tracking-tight text-foreground">
            Verification overview
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Every claim the backend has investigated, with its evidence status, the
            sources it quotes, and the calculations that code ran.
          </p>
        </header>
        <BackendNotice error={error} empty={traces.length === 0} />

        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard
            label="Findings"
            value={String(agg.total)}
            hint="all time"
          />
          <StatCard
            label="Avg. checklist coverage"
            value={`${agg.averageCoverage}%`}
            hint="questions answered, not a confidence level"
          />
          <StatCard
            label="Contradiction rate"
            value={`${agg.contradictionRate}%`}
            hint="claims contradicted"
          />
          <StatCard
            label="Independent evidence"
            value={`${agg.independentShare}%`}
            hint="of cited sources"
          />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1.1fr_1fr]">
          <Panel>
            <PanelTitle>Verdict distribution</PanelTitle>
            <div className="mt-5">
              <VerdictDonut counts={agg.verdictCounts} total={agg.total} />
            </div>
          </Panel>
          <Panel>
            <PanelTitle>Daily analysis volume</PanelTitle>
            <div className="mt-5">
              <VolumeBars daily={agg.daily} />
            </div>
          </Panel>
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1.1fr]">
          <Panel>
            <PanelTitle>Most common failure patterns</PanelTitle>
            <p className="mt-1 mb-4 text-xs text-muted-foreground">
              Overstatement mechanisms named across all findings.
            </p>
            <TagBars tags={agg.tagCounts} />
          </Panel>

          <Panel className="p-0">
            <div className="flex items-center justify-between px-5 pt-5">
              <PanelTitle>Recent traces</PanelTitle>
              <Link
                href="/traces"
                className="inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
              >
                View all
                <ArrowUpRight className="size-3.5" />
              </Link>
            </div>
            <ul className="mt-3 divide-y divide-border">
              {recent.map((t) => (
                <li key={t.id}>
                  <Link
                    href={`/traces/${t.id}`}
                    className="flex flex-col gap-2 px-5 py-3.5 transition-colors hover:bg-secondary/50"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <p className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
                        {t.claim}
                      </p>
                      <VerdictBadge verdict={t.verdict} />
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="w-32 shrink-0 truncate text-xs text-muted-foreground">
                        {t.source}
                      </span>
                      <CoverageMeter value={t.coverage} className="flex-1" />
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>
    </AppShell>
  )
}
