import { AppShell } from "@/components/app-shell"
import { BackendNotice } from "@/components/backend-notice"
import { TracesExplorer } from "@/components/traces-explorer"
import { getTraces } from "@/lib/live"

export const dynamic = "force-dynamic"

export default async function TracesPage() {
  const { traces, error } = await getTraces()
  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-8">
        <header className="mb-6">
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Traces
          </p>
          <h1 className="mt-1 font-serif text-4xl tracking-tight text-foreground">
            All findings
          </h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Every claim the backend has investigated. Filter by status, search across sources and
            mechanisms, then open a finding to inspect its evidence.
          </p>
        </header>
        <BackendNotice error={error} empty={traces.length === 0} />
        <TracesExplorer traces={traces} />
      </div>
    </AppShell>
  )
}
