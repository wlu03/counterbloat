import { notFound } from "next/navigation"
import { AppShell } from "@/components/app-shell"
import { TraceDetail } from "@/components/trace-detail"
import { getTrace } from "@/lib/live"

export const dynamic = "force-dynamic"

export default async function TracePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params
  const found = await getTrace(decodeURIComponent(id))
  if (!found) notFound()

  return (
    <AppShell>
      <TraceDetail trace={found.trace} score={found.score} />
    </AppShell>
  )
}
