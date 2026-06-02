'use client'

import { AppTopbar, type QuickLink } from '@/components/nav/AppTopbar'
import { Sidebar } from '@/components/nav/Sidebar'
import { TENANT_NAV_ITEMS } from '@/components/nav/nav-items'
import { cn } from '@/lib/utils'
import { usePathname } from 'next/navigation'
import type { ReactNode } from 'react'
import { useMemo, useState } from 'react'

interface DashboardShellProps {
  children: ReactNode
  userEmail?: string
}

export function DashboardShell({ children, userEmail }: DashboardShellProps) {
  const pathname = usePathname()
  const [collapsed, setCollapsed] = useState(false)
  const tenantMatch = pathname.match(/\/tenants\/([^/]+)/)
  const activeTenantId = tenantMatch?.[1] ?? null

  const quickLinks = useMemo<QuickLink[]>(() => {
    const links: QuickLink[] = [
      {
        label: 'Cola general',
        href: '/',
        description: 'Pendientes cross-tenant',
      },
    ]

    if (!activeTenantId) return links

    return [
      ...links,
      ...TENANT_NAV_ITEMS.map((item) => ({
        label: item.label,
        href: `/tenants/${activeTenantId}/${item.section}`,
        description: item.keywords.join(', '),
      })),
    ]
  }, [activeTenantId])

  return (
    <div data-density="compact" data-theme="mercury" className="min-h-screen bg-background">
      <Sidebar userEmail={userEmail} collapsed={collapsed} onCollapsedChange={setCollapsed} />
      <div
        className={cn(
          'min-h-screen transition-[margin-left] duration-200 ease-out',
          collapsed ? 'ml-[60px]' : 'ml-[236px]',
        )}
      >
        <AppTopbar
          actionHref={activeTenantId ? `/tenants/${activeTenantId}/proposals` : undefined}
          actionLabel="Revisar mejoras"
          placeholder="Buscar secciones, clientes, AOPs..."
          quickLinks={quickLinks}
        />
        <main className="px-6 pb-8 pt-10">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </div>
  )
}
