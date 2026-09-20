import { cn } from "@/lib/utils"

export function Panel({
  children,
  className,
  id,
}: {
  children: React.ReactNode
  className?: string
  id?: string
}) {
  return (
    <section
      id={id}
      className={cn(
        "rounded-xl border border-border bg-card p-5 shadow-[0_1px_2px_rgba(0,0,0,0.03)]",
        className,
      )}
    >
      {children}
    </section>
  )
}

export function PanelTitle({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <h2
      className={cn(
        "text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground",
        className,
      )}
    >
      {children}
    </h2>
  )
}

export function StatCard({
  label,
  value,
  hint,
}: {
  label: string
  value: string
  hint?: string
}) {
  return (
    <Panel className="flex flex-col gap-1">
      <span className="text-[0.7rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {label}
      </span>
      <span className="font-serif text-3xl leading-none text-foreground">
        {value}
      </span>
      {hint && <span className="text-xs text-muted-foreground">{hint}</span>}
    </Panel>
  )
}
