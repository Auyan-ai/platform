'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'
import { TenantSwitcher } from './TenantSwitcher'
import { LogoutButton } from './LogoutButton'

const NAV_ITEMS = [
  { label: 'Conversaciones', icon: '💬', section: 'conversations' },
  { label: 'Escalaciones', icon: '🚨', section: 'escalations' },
]

interface SidebarProps {
  userEmail?: string
}

export function Sidebar({ userEmail }: SidebarProps) {
  const pathname = usePathname()
  const tenantMatch = pathname.match(/\/tenants\/([^/]+)/)
  const activeTenantId = tenantMatch?.[1] ?? null

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-60 flex-col bg-white border-r border-neutral-200">
      <div className="flex h-14 items-center border-b border-neutral-200 px-4">
        <span className="text-sm font-semibold tracking-tight">Auyan</span>
      </div>

      <div className="p-3 border-b border-neutral-100">
        <p className="px-2 mb-1 text-xs font-medium text-neutral-400 uppercase tracking-wider">
          Tenant
        </p>
        <TenantSwitcher activeTenantId={activeTenantId} />
      </div>

      <nav className="flex-1 overflow-y-auto p-3 space-y-1 text-sm">
        {activeTenantId &&
          NAV_ITEMS.map(({ label, icon, section }) => {
            const href = `/tenants/${activeTenantId}/${section}`
            const isActive = pathname.startsWith(href)
            return (
              <Link
                key={section}
                href={href}
                className={cn(
                  'flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors',
                  isActive
                    ? 'bg-neutral-100 text-neutral-900 font-medium'
                    : 'text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900',
                )}
              >
                <span>{icon}</span> {label}
              </Link>
            )
          })}
      </nav>

      <LogoutButton email={userEmail} />
    </aside>
  )
}
