'use client'

import { cn } from '@/lib/utils'
import {
  AlertTriangle,
  BookOpenText,
  CheckCircle2,
  FileBarChart2,
  FileText,
  FlaskConical,
  Mail,
  MessagesSquare,
  ScrollText,
  Sparkles,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LogoutButton } from './LogoutButton'
import { TenantSwitcher } from './TenantSwitcher'

const NAV_ITEMS = [
  { label: 'Conversaciones', icon: MessagesSquare, section: 'conversations' },
  { label: 'Escalaciones', icon: AlertTriangle, section: 'escalations' },
  { label: 'Aprobaciones', icon: CheckCircle2, section: 'approvals' },
  { label: 'Playbook', icon: BookOpenText, section: 'playbook' },
  { label: 'KB Review', icon: FileText, section: 'knowledge' },
  { label: 'Reportes', icon: FileBarChart2, section: 'reports' },
  { label: 'Emails', icon: Mail, section: 'emails' },
  { label: 'AOPs', icon: ScrollText, section: 'aops' },
  { label: 'Mejoras propuestas', icon: Sparkles, section: 'proposals' },
  { label: 'Simulator', icon: FlaskConical, section: 'simulator' },
] as const

interface SidebarProps {
  userEmail?: string
}

export function Sidebar({ userEmail }: SidebarProps) {
  const pathname = usePathname()
  const tenantMatch = pathname.match(/\/tenants\/([^/]+)/)
  const activeTenantId = tenantMatch?.[1] ?? null

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-[200px] flex-col border-r border-border bg-surface-muted">
      <div className="flex h-14 items-center border-b border-border px-4">
        <span className="text-sm font-semibold tracking-tight text-foreground">Auyan</span>
      </div>

      <div className="border-b border-border-subtle p-2">
        <p className="mb-1 px-2 text-[11px] font-medium uppercase tracking-wider text-foreground-muted">
          Tenant
        </p>
        <TenantSwitcher activeTenantId={activeTenantId} />
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2 text-sm">
        {activeTenantId &&
          NAV_ITEMS.map(({ label, icon: Icon, section }) => {
            const href = `/tenants/${activeTenantId}/${section}`
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
