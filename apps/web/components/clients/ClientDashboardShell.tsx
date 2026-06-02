'use client'

import { ClientSidebar } from '@/components/clients/ClientSidebar'
import { cn } from '@/lib/utils'
import type { ReactNode } from 'react'
import { useState } from 'react'

interface ClientDashboardShellProps {
  children: ReactNode
  tenantId: string
  tenantName: string
  lifecycleState: string
  userEmail?: string
}

export function ClientDashboardShell({
  children,
  tenantId,
  tenantName,
  lifecycleState,
  userEmail,
}: ClientDashboardShellProps) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <>
      <ClientSidebar
        tenantId={tenantId}
        tenantName={tenantName}
        lifecycleState={lifecycleState}
        userEmail={userEmail}
        collapsed={collapsed}
        onCollapsedChange={setCollapsed}
      />
      <div
        className={cn(
          'min-h-screen transition-[margin-left] duration-200 ease-out',
          collapsed ? 'ml-[60px]' : 'ml-[236px]',
        )}
      >
        <main className="px-6 pb-8 pt-10">
          <div className="mx-auto max-w-6xl">{children}</div>
        </main>
      </div>
    </>
  )
}
