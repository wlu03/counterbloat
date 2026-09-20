"use client"

import Link from "next/link"
import { useEffect, useRef, useState } from "react"
import { ArrowUpRight, FlaskConical, LoaderCircle } from "lucide-react"
import { api } from "@/lib/api"
import { Panel, PanelTitle } from "@/components/panel"
import { VerdictBadge } from "@/components/verdict-badge"
import type { Verdict } from "@/lib/types"

const REPOSITORY = /https?:\/\/(?:www\.)?(?:github|gitlab)\.com\/[\w.-]+\/[\w.-]+/

type Job = { id: string; status: string; partial?: boolean; errors: string[]; claims_total?: number; claims_done?: number }
type Finding = { finding_id: string; claim_id: string; evidence_status: string; summary: string }
type Call = { provider: string; acus: number | null; latency_ms: number | null; error: string | null }
type TraceRecord = { claim: string; usage: { replications: Call[] } }

const VERDICTS: Record<string, Verdict> = {
  supported: "supported", contradicted: "contradicted", mixed: "partially_supported",
  insufficient: "unverifiable", not_yet_resolvable: "unverifiable",
}

export function PostWorkflow() {
  const [text, setText] = useState("")
  const [replicate, setReplicate] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  const [findings, setFindings] = useState<(Finding & TraceRecord)[]>([])
  const [problem, setProblem] = useState("")
  const [busy, setBusy] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const repository = text.match(REPOSITORY)?.[0] ?? null
  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])

  async function poll(id: string) {
    const current = await api<Job>(`analyses/${id}`)
    setJob(current)
    if (current.status === "queued" || current.status === "running") {
      timer.current = setTimeout(() => poll(id).catch((e) => setProblem(String(e))), 3000)
      return
    }
    const found = await api<Finding[]>(`analyses/${id}/findings`)
    const records = await Promise.all(found.map((f) => api<TraceRecord>(`traces/${encodeURIComponent(f.finding_id)}`)))
    setFindings(found.map((f, i) => ({ ...f, ...records[i] })))
    setBusy(false)
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setProblem("")
    setFindings([])
    setJob(null)
    try {
      const document = await api<{ id: string }>("documents", { content: text, media_type: "text/plain" })
      const created = await api<Job>("analyses", { document_id: document.id, replicate },
        { "Idempotency-Key": crypto.randomUUID() })
      await poll(created.id)
    } catch (e) {
      setProblem(String(e))
      setBusy(false)
    }
  }

  const replication = findings[0]?.usage.replications[0]

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_1.2fr] lg:items-start">
      <Panel>
        <PanelTitle>The post</PanelTitle>
        <form onSubmit={submit} className="mt-3 flex flex-col gap-3">
          <label htmlFor="post" className="text-sm text-muted-foreground">
            Paste the text of the post, including the link to its repository. Nothing here fetches
            from X.
          </label>
          <textarea
            id="post" rows={8} value={text} onChange={(e) => setText(e.target.value)}
            className="w-full rounded-lg border border-border bg-card p-3 text-sm text-foreground"
            placeholder="We open-sourced … It reaches 92% accuracy on … Code: https://github.com/…"
          />
          <p className="text-xs text-muted-foreground">
            {repository ? `Repository found: ${repository}` : "No GitHub or GitLab link found in the text yet."}
          </p>
          <label className="flex items-start gap-2 text-sm text-foreground">
            <input
              type="checkbox" className="mt-1" checked={replicate} disabled={!repository}
              onChange={(e) => setReplicate(e.target.checked)}
            />
            <span>
              Run the repository&apos;s code in one Devin session to test the claims. This is paid, can
              take up to an hour, and runs that code in Devin&apos;s sandbox with none of your stored
              secrets.
            </span>
          </label>
          <button
            disabled={busy || !text.trim()}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-foreground px-4 py-2 text-sm font-medium text-background disabled:opacity-50"
          >
            {busy ? <LoaderCircle className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
            {busy ? "Working" : "Check the post"}
          </button>
          {problem && <p role="alert" className="text-sm text-contradicted">{problem}</p>}
        </form>
      </Panel>

      <Panel>
        <PanelTitle>Result</PanelTitle>
        {!job && <p className="mt-3 text-sm text-muted-foreground">Nothing has been checked yet.</p>}
        {job && (
          <p role="status" className="mt-3 text-sm text-foreground">
            Analysis {job.status}{job.partial ? " (partial)" : ""}.
            {job.claims_total !== undefined && ` ${job.claims_done ?? 0} of ${job.claims_total} claims investigated.`}
            {replicate && busy && " A replication can take many minutes."}
          </p>
        )}
        {job?.errors.map((e) => (
          <p key={e} className="mt-2 rounded-lg border border-border bg-secondary/40 px-3 py-2 text-xs text-muted-foreground">{e}</p>
        ))}
        {replication && (
          <p className="mt-3 text-xs text-muted-foreground">
            Devin session: {replication.error ? `no result (${replication.error})` : "report stored as a source"}
            {replication.latency_ms ? `, ${Math.round(replication.latency_ms / 1000)} s` : ""}
            {replication.acus !== null ? `, ${replication.acus} ACUs reported at the end of the session` : ""}.
            A replication that gave no result is not evidence against a claim.
          </p>
        )}
        {job && !busy && findings.length === 0 && (
          <p className="mt-3 text-sm text-muted-foreground">No checkable claim was found in the text.</p>
        )}
        <ul className="mt-3 flex flex-col gap-3">
          {findings.map((f) => (
            <li key={f.finding_id} className="rounded-lg border border-border p-3.5">
              <div className="flex items-start justify-between gap-3">
                <p className="font-serif text-base leading-snug text-foreground">{f.claim}</p>
                <VerdictBadge verdict={VERDICTS[f.evidence_status] ?? "unverifiable"} />
              </div>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{f.summary}</p>
              <Link
                href={`/traces/${encodeURIComponent(f.finding_id)}`}
                className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
              >
                Evidence, calculations, and sources <ArrowUpRight className="size-3.5" />
              </Link>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}
