import { cn } from "@/lib/utils"
import { VERDICT_LABELS, type Verdict } from "@/lib/types"

const styles: Record<Verdict, string> = {
  supported: "bg-supported-bg text-supported border-supported/25",
  contradicted: "bg-contradicted-bg text-contradicted border-contradicted/25",
  partially_supported: "bg-partial-bg text-partial border-partial/30",
  unverifiable: "bg-unverifiable-bg text-unverifiable border-unverifiable/25",
}

export function VerdictBadge({
  verdict,
  className,
  size = "sm",
}: {
  verdict: Verdict
  className?: string
  size?: "sm" | "md"
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border font-medium uppercase tracking-wide",
        size === "sm" ? "px-2 py-0.5 text-[0.68rem]" : "px-2.5 py-1 text-xs",
        styles[verdict],
        className,
      )}
    >
      <span
        className="size-1.5 rounded-full bg-current"
        aria-hidden="true"
      />
      {VERDICT_LABELS[verdict]}
    </span>
  )
}
