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
          Real calls and real filings. A run reads the call, chases each claim into the annual
          report for the same period, and checks any named figure against what the company filed.
          The score beside a claim is accumulated from that evidence under a neutral prior. It is
          not fitted to any outcome, so it says how the evidence adds up and not how often such a
          claim turns out to be wrong.
        </p>
        <TranscriptWorkflow />
      </div>
    </AppShell>
  )
}
