'use client'

import { useState } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useAdminTenants } from '@/lib/api/hooks/tenants'
import type { components } from '@auyan/shared/api-types'

type TenantResponse = components['schemas']['TenantResponse']

const STATUS_DOT: Record<string, string> = {
  active: 'bg-success',
  inactive: 'bg-border-strong',
  suspended: 'bg-danger',
}

export function TenantSwitcher({ activeTenantId }: { activeTenantId: string | null }) {
  const [open, setOpen] = useState(false)
  const router = useRouter()
  const pathname = usePathname()
  const { data: tenants, isLoading } = useAdminTenants()

  const active = tenants?.find((t) => t.id === activeTenantId)

  function selectTenant(tenant: TenantResponse) {
    setOpen(false)
    const section =
      pathname.match(/\/tenants\/[^/]+\/(conversations|escalations)/)?.[1] ?? 'conversations'
    router.push(`/tenants/${tenant.id}/${section}`)
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 rounded-sm px-2 py-1.5 text-sm text-left hover:bg-surface-muted transition-colors"
      >
        <span className="flex-1 truncate font-medium text-foreground-body">
          {isLoading ? '…' : active?.name ?? 'Selecciona tenant'}
        </span>
        {open ? (
          <ChevronUp className="size-3.5 text-foreground-subtle" />
        ) : (
          <ChevronDown className="size-3.5 text-foreground-subtle" />
        )}
      </button>

      {open && tenants && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 rounded-md border border-border bg-surface-elevated shadow-sm overflow-hidden">
          {tenants.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => selectTenant(t)}
              className={cn(
                'w-full flex items-center gap-2 px-3 py-2 text-sm text-left hover:bg-surface-muted transition-colors',
                t.id === activeTenantId && 'bg-surface-muted font-medium text-foreground',
              )}
            >
              <span
                className={cn(
                  'shrink-0 h-1.5 w-1.5 rounded-full',
                  STATUS_DOT[t.status] ?? 'bg-border-strong',
                )}
                aria-label={t.status}
              />
              <span className="truncate text-foreground-body">{t.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
