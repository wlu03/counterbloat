import { AppShell } from "@/components/app-shell"
import { TranscriptWorkflow } from "@/components/transcript-workflow"

export const metadata = {
  title: "Discover transcripts · Countercheck",
  description:
    "Search recent earnings-call transcripts and run the overstatement-detection workflow.",
}

export default function TranscriptsPage() {
  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-8">
        <header className="mb-6 flex flex-col gap-1.5">
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Discover
          </p>
          <h1 className="font-serif text-3xl text-foreground">
            Transcripts &amp; overstatement runs
          </h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Every claim from an earnings call is chased into the matching 10-K by
            read-only search agents and scored against the speaker&apos;s own
            words. Pick a recent call and run the pipeline to produce a
            per-claim ledger with linked evidence.
          </p>
        </header>
        <p role="note" className="mb-4 rounded-lg border border-dashed border-border bg-secondary/40 px-4 py-3 text-sm text-foreground">
          Sample data. This page is not connected to the backend yet. The companies are invented,
          and the transcripts, agent runs, scores, and verdicts shown here were written by hand to
          show the intended workflow. They are not results of any analysis.
        </p>
        <TranscriptWorkflow />
      </div>
    </AppShell>
  )
}
