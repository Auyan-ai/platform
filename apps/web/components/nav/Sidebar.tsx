'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import {
  MessagesSquare,
  AlertTriangle,
  CheckCircle2,
  ScrollText,
  Sparkles,
  FlaskConical,
  BookOpenText,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { TenantSwitcher } from './TenantSwitcher'
import { LogoutButton } from './LogoutButton'

const NAV_ITEMS = [
  { label: 'Conversaciones', icon: MessagesSquare, section: 'conversations' },
  { label: 'Escalaciones', icon: AlertTriangle, section: 'escalations' },
  { label: 'Aprobaciones', icon: CheckCircle2, section: 'approvals' },
  { label: 'Playbook', icon: BookOpenText, section: 'playbook' },
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
    <aside className="fixed inset-y-0 left-0 z-50 flex w-60 flex-col bg-surface border-r border-border">
      <div className="flex h-14 items-center border-b border-border px-4">
        <span className="text-sm font-semibold tracking-tight text-foreground">Auyan</span>
      </div>

      <div className="p-3 border-b border-border-subtle">
        <p className="px-2 mb-1 text-xs font-medium text-foreground-muted uppercase tracking-wider">
          Tenant
        </p>
        <TenantSwitcher activeTenantId={activeTenantId} />
      </div>

      <nav className="flex-1 overflow-y-auto p-3 space-y-0.5 text-sm">
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
                    ? 'bg-accent-subtle text-accent-foreground font-medium'
                    : 'text-foreground-body hover:bg-surface-muted hover:text-foreground',
                )}
              >
                <Icon className="size-4 shrink-0" />
                <span>{label}</span>
              </Link>
            )
          })}
      </nav>

      <LogoutButton email={userEmail} />
    </aside>
  )
}
