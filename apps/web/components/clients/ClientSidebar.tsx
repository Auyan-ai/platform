'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { label: 'Overview', icon: '📊', section: 'overview' },
  { label: 'Conversaciones', icon: '💬', section: 'conversations' },
  { label: 'Escalaciones', icon: '🚨', section: 'escalations' },
]

interface ClientSidebarProps {
  tenantId: string
  tenantName: string
}

export function ClientSidebar({ tenantId, tenantName }: ClientSidebarProps) {
  const pathname = usePathname()

  return (
    <aside className="fixed inset-y-0 left-0 z-50 flex w-60 flex-col border-r border-neutral-200 bg-white">
      <div className="flex h-14 items-center border-b border-neutral-200 px-4">
        <span className="text-sm font-semibold tracking-tight">Auyan</span>
      </div>

      <div className="border-b border-neutral-100 px-4 py-3">
        <p className="mb-0.5 text-xs font-medium uppercase tracking-wider text-neutral-400">
          Cliente
        </p>
        <p className="truncate text-sm font-medium text-neutral-900">{tenantName}</p>
      </div>

      <nav className="flex-1 space-y-1 overflow-y-auto p-3 text-sm">
        {NAV_ITEMS.map(({ label, icon, section }) => {
          const href = `/clients/${tenantId}/${section}`
          const isActive = pathname.startsWith(href)
          return (
            <Link
              key={section}
              href={href}
              className={cn(
                'flex items-center gap-2 rounded-lg px-2 py-1.5 transition-colors',
                isActive
                  ? 'bg-neutral-100 font-medium text-neutral-900'
                  : 'text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900',
              )}
            >
              <span>{icon}</span> {label}
            </Link>
          )
        })}
      </nav>
    </aside>
  )
}
