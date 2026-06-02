'use client'

import { Sidebar } from '@/components/nav/Sidebar'
import { cn } from '@/lib/utils'
import type { ReactNode } from 'react'
import { useState } from 'react'

interface DashboardShellProps {
  children: ReactNode
  userEmail?: string
}

export function DashboardShell({ children, userEmail }: DashboardShellProps) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <div data-density="compact" data-theme="mercury" className="min-h-screen bg-background">
      <Sidebar userEmail={userEmail} collapsed={collapsed} onCollapsedChange={setCollapsed} />
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
    </div>
  )
}
