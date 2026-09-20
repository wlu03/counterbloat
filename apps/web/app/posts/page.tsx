import { AppShell } from "@/components/app-shell"
import { PostWorkflow } from "@/components/post-workflow"

export const metadata = {
  title: "Reproduce a post · Countercheck",
  description:
    "Paste a post that links to code, extract its claims, and let Devin clone and run the repository to measure whether the claims hold.",
}

export default function PostsPage() {
  return (
    <AppShell>
      <div className="mx-auto max-w-6xl px-6 py-8">
        <header className="mb-6 flex flex-col gap-1.5">
          <p className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Reproduce
          </p>
          <h1 className="font-serif text-3xl text-foreground">Verify a post that links to code</h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Paste the text of a post that links to a repository. Countercheck extracts the claims
            it makes, such as &ldquo;reaches 92% accuracy on this benchmark.&rdquo; If you opt in, Devin
            clones the linked repository, runs the code, and reports what it measured. That report
            becomes a source the finding can quote. A run that could not be completed is not
            counted against a claim.
          </p>
        </header>
        <PostWorkflow />
      </div>
    </AppShell>
  )
}
