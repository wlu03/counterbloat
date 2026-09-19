"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { EvidenceDrawer } from "@/components/EvidenceDrawer";
import { FindingPanel } from "@/components/FindingPanel";
import { InvestigationView } from "@/components/InvestigationView";
import { Reader } from "@/components/Reader";
import { api, type ClaimDetail, type Finding, type Span } from "@/lib/api";

type Job = { id: string; document_id: string; status: string; errors: string[]; partial?: boolean };

export default function AnalysisPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [spans, setSpans] = useState<Span[]>([]);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [details, setDetails] = useState<Record<string, ClaimDetail>>({});
  const [updates, setUpdates] = useState<Record<string, never[]>>({});
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      const current = await api<Job>(`analyses/${id}`);
      setJob(current);
      if (spans.length === 0) {
        setSpans((await api<{ spans: Span[] }>(`documents/${current.document_id}`)).spans);
      }
      const found = await api<Finding[]>(`analyses/${id}/findings`);
      setFindings(found);
      for (const finding of found) {
        const detail = await api<ClaimDetail>(`claims/${finding.claim_id}`);
        const history = await api<never[]>(`claims/${finding.claim_id}/updates`);
        setDetails((d) => ({ ...d, [finding.claim_id]: detail }));
        setUpdates((u) => ({ ...u, [finding.claim_id]: history }));
      }
      if (current.status === "queued" || current.status === "running") timer = setTimeout(load, 2000);
    }
    load();
    return () => clearTimeout(timer);
  }, [id]);

  const finding = findings.find((f) => f.claim_id === selected) ?? findings[0];
  const detail = finding ? details[finding.claim_id] : undefined;

  return (
    <main>
      <p role="status">Analysis {job?.status ?? "loading"}{job?.partial ? " (partial)" : ""}.
        {job?.errors?.length ? ` ${job.errors.length} operational errors recorded.` : ""}{" "}
        <a href={`/api/backend/analyses/${id}/export`}>Export JSON</a></p>
      <div className="layout">
        <Reader spans={spans} claims={Object.values(details).map((d) => d.claim)} findings={findings}
          selected={finding?.claim_id ?? null} onSelect={setSelected} />
        <aside>
          {finding ? <FindingPanel finding={finding} /> : <p>No findings yet.</p>}
          {detail && <EvidenceDrawer evidence={detail.evidence} calculations={detail.calculations} />}
          {detail && <InvestigationView questions={detail.questions} coverage={detail.coverage}
            updates={updates[finding!.claim_id] ?? []} stopReason={detail.stop_reason} />}
        </aside>
      </div>
    </main>
  );
}
