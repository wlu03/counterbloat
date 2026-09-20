import { cn } from "@/lib/utils"

function toneFor(value: number) {
  if (value >= 80) return "text-supported"
  if (value >= 60) return "text-partial"
  if (value >= 45) return "text-unverifiable"
  return "text-contradicted"
}

function barFor(value: number) {
  if (value >= 80) return "bg-supported"
  if (value >= 60) return "bg-partial"
  if (value >= 45) return "bg-unverifiable"
  return "bg-contradicted"
}

/** Share of checklist questions answered. It is a measure of how much was checked, not of confidence. */
export function CoverageMeter({
  value,
  className,
  showLabel = true,
}: {
  value: number
  className?: string
  showLabel?: boolean
}) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-border">
        <div
          className={cn("h-full rounded-full", barFor(value))}
          style={{ width: `${value}%` }}
        />
      </div>
      {showLabel && (
        <span
          className={cn(
            "w-9 shrink-0 text-right text-sm font-semibold tabular-nums",
            toneFor(value),
          )}
        >
          {value}
        </span>
      )}
    </div>
  )
}
