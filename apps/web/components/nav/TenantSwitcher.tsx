'use client'

import { useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'
import { useAdminTenants } from '@/lib/api/hooks/tenants'
import type { components } from '@auyan/shared/api-types'

type TenantResponse = components['schemas']['TenantResponse']

const STATUS_DOT: Record<string, string> = {
  active: 'bg-green-400',
  inactive: 'bg-neutral-300',
  suspended: 'bg-red-400',
}

export function TenantSwitcher({ activeTenantId }: { activeTenantId: string | null }) {
  const [open, setOpen] = useState(false)
  const router = useRouter()
  const pathname = usePathname()
  const { data: tenants, isLoading } = useAdminTenants()

  const active = tenants?.find((t) => t.id === activeTenantId)

  function selectTenant(tenant: TenantResponse) {
    setOpen(false)
    // Keep the current sub-section (conversations/escalations) when switching tenant
    const section = pathname.match(/\/tenants\/[^/]+\/(conversations|escalations)/)?.[1] ?? 'conversations'
    router.push(`/tenants/${tenant.id}/${section}`)
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-left hover:bg-neutral-100"
      >
        <span className="flex-1 truncate font-medium text-neutral-800">
          {isLoading ? '…' : active?.name ?? 'Selecciona tenant'}
        </span>
        <span className="text-neutral-400 text-xs">{open ? '▲' : '▼'}</span>
      </button>

      {open && tenants && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-xl border border-neutral-200 bg-white shadow-lg overflow-hidden">
          {tenants.map((t) => (
            <button
              key={t.id}
              onClick={() => selectTenant(t)}
              className={cn(
                'w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-neutral-50',
                t.id === activeTenantId && 'bg-neutral-50 font-medium',
              )}
            >
              <span
                className={cn(
                  'shrink-0 h-1.5 w-1.5 rounded-full',
                  STATUS_DOT[t.status] ?? 'bg-neutral-300',
                )}
              />
              <span className="truncate">{t.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
