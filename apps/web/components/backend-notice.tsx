import Link from "next/link"

/** Says why a page has nothing to show: the backend is unreachable, or nothing was analysed yet. */
export function BackendNotice({ error, empty }: { error: string | null; empty: boolean }) {
  if (!error && !empty) return null
  return (
    <p role="status" className="mb-4 rounded-lg border border-border bg-secondary/40 px-4 py-3 text-sm text-foreground">
      {error
        ? `The backend could not be reached, so no findings are shown. ${error}`
        : "No document has been analysed yet. "}
      {!error && <Link href="/analyze" className="font-medium text-accent underline-offset-2 hover:underline">Analyze a document</Link>}
    </p>
  )
}
