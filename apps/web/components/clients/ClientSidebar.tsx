'use client'

import { LogoutButton } from '@/components/nav/LogoutButton'
import { cn } from '@/lib/utils'
import {
  AlertTriangle,
  ClipboardList,
  FileBarChart2,
  FileText,
  LayoutDashboard,
  MessagesSquare,
  Store,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'

const NAV_ITEMS = [
  { label: 'Overview', icon: LayoutDashboard, section: 'overview' },
  { label: 'Onboarding', icon: ClipboardList, section: 'onboarding' },
  { label: 'Datos', icon: Store, section: 'facts' },
  { label: 'Conocimiento', icon: FileText, section: 'knowledge' },
  { label: 'Reportes', icon: FileBarChart2, section: 'reports' },
  { label: 'Conversaciones', icon: MessagesSquare, section: 'conversations' },
  { label: 'Escalaciones', icon: AlertTriangle, section: 'escalations' },
] as const

interface ClientSidebarProps {
  tenantId: string
  tenantName: string
  userEmail?: string
}

export function ClientSidebar({ tenantId, tenantName, userEmail }: ClientSidebarProps) {
  const pathname = usePathname()

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-[200px] flex-col border-r border-border bg-surface-muted">
      <div className="flex h-14 items-center border-b border-border px-4">
        <span className="text-sm font-semibold tracking-tight text-foreground">Auyan</span>
      </div>

      <div className="border-b border-border-subtle px-4 py-3">
        <p className="mb-0.5 text-[11px] font-medium uppercase tracking-wider text-foreground-muted">
          Cliente
        </p>
        <p className="truncate text-sm font-medium text-foreground">{tenantName}</p>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2 text-sm">
        {NAV_ITEMS.map(({ label, icon: Icon, section }) => {
          const href = `/clients/${tenantId}/${section}`
          const isActive = pathname.startsWith(href)
          return (
            <Link
              key={section}
              href={href}
              className={cn(
                'flex items-center gap-2.5 rounded-sm px-2 py-1.5 transition-colors',
                isActive
                  ? 'bg-border-subtle font-medium text-foreground'
                  : 'text-foreground-body hover:bg-border-subtle hover:text-foreground',
              )}
            >
              <Icon className="size-3.5 shrink-0 text-foreground-muted" />
              <span>{label}</span>
            </Link>
          )
        })}
      </nav>

      <LogoutButton email={userEmail} />
    </aside>
  )
}
