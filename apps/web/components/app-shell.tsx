"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { LayoutDashboard, ListChecks, FileSearch, AudioLines, FlaskConical } from "lucide-react"
import { cn } from "@/lib/utils"

const nav = [
  { href: "/", label: "Overview", icon: LayoutDashboard, exact: true },
  { href: "/traces", label: "Traces", icon: ListChecks, exact: false },
  { href: "/analyze", label: "Analyze", icon: FileSearch, exact: false },
  { href: "/transcripts", label: "Discover", icon: AudioLines, exact: false },
  { href: "/posts", label: "Reproduce", icon: FlaskConical, exact: false },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()

  return (
    <div className="flex min-h-svh flex-col bg-background md:flex-row">
      <aside className="flex shrink-0 flex-col border-b border-border md:w-64 md:border-r md:border-b-0">
        <div className="flex items-center gap-2 px-5 py-5">
          <span className="rounded-md border-2 border-foreground px-2 py-0.5 text-lg font-bold tracking-tight text-foreground font-serif">
            Countercheck
          </span>
        </div>
        <nav className="flex gap-1 px-3 pb-3 md:flex-col md:pb-0">
          {nav.map((item) => {
            const active = item.exact
              ? pathname === item.href
              : pathname.startsWith(item.href)
            const Icon = item.icon
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-secondary text-foreground"
                    : "text-muted-foreground hover:bg-secondary/60 hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                {item.label}
              </Link>
            )
          })}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  )
}
