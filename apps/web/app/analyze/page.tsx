"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { AppShell } from "@/components/app-shell";
import { api } from "@/lib/api";
import "./reader.css";

export default function Home() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [content, setContent] = useState("");
  const [replicate, setReplicate] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const document = await api<{ id: string }>("documents", url ? { url } : { content });
      const job = await api<{ id: string }>("analyses", { document_id: document.id, replicate },
        { "Idempotency-Key": crypto.randomUUID() });
      router.push(`/analyses/${job.id}`);
    } catch (problem) {
      setError(String(problem));
      setBusy(false);
    }
  }

  return (
    <AppShell>
    <div className="cc-reader">
    <main>
      <form className="form" onSubmit={submit}>
        <label htmlFor="url">Document URL</label>
        <input id="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://" />
        <label htmlFor="content">Or paste HTML or text</label>
        <textarea id="content" rows={10} value={content} onChange={(e) => setContent(e.target.value)} />
        <label>
          <input type="checkbox" checked={replicate} onChange={(e) => setReplicate(e.target.checked)} />{" "}
          If the text links a GitHub or GitLab repository, run its code in one Devin session to test
          the claims. This is paid, can take up to an hour, and runs code from that repository in
          Devin&apos;s sandbox.
        </label>
        <button disabled={busy || !(url || content)}>{busy ? "Submitting" : "Analyze"}</button>
        {error && <p role="alert">{error}</p>}
      </form>
    </main>
    </div>
    </AppShell>
  );
}
